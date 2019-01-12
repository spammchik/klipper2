# BLTouch support
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import math, logging
import homing, probe, mcu

SIGNAL_PERIOD = 0.025600
MIN_CMD_TIME = 4 * SIGNAL_PERIOD

TEST_TIME = 5 * 60.
ENDSTOP_REST_TIME = .001
ENDSTOP_SAMPLE_TIME = .000015
ENDSTOP_SAMPLE_COUNT = 4

Commands = {
    None: 0.0, 'pin_down': 0.000700, 'touch_mode': 0.001200,
    'pin_up': 0.001500, 'self_test': 0.001800, 'reset': 0.002200,
}

# BLTouch "endstop" wrapper
class BLTouchEndstopWrapper:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.position_endstop = config.getfloat('z_offset')
        # Create a pwm object to handle the control pin
        ppins = self.printer.lookup_object('pins')
        self.mcu_pwm = ppins.setup_pin('pwm', config.get('control_pin'))
        self.mcu_pwm.setup_max_duration(0.)
        self.mcu_pwm.setup_cycle_time(SIGNAL_PERIOD)
        # Create an "endstop" object to handle the sensor pin
        pin = config.get('sensor_pin')
        pin_params = ppins.lookup_pin(pin, can_invert=True, can_pullup=True)
        mcu = pin_params['chip']
        mcu.register_config_callback(self._build_config)
        self.mcu_endstop = mcu.setup_pin('endstop', pin_params)
        # Setup for sensor test
        self.next_test_time = 0.
        self.test_sensor_pin = config.getboolean('test_sensor_pin', True)
        # Calculate pin move time
        pmt = max(config.getfloat('pin_move_time', 1.0), MIN_CMD_TIME)
        self.pin_move_time = math.ceil(pmt / SIGNAL_PERIOD) * SIGNAL_PERIOD
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self.mcu_endstop.get_steppers
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop
        self.query_endstop_wait = self.mcu_endstop.query_endstop_wait
        self.TimeoutError = self.mcu_endstop.TimeoutError
        # Register BLTOUCH_DEBUG command
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command("BLTOUCH_DEBUG", self.cmd_BLTOUCH_DEBUG,
                                    desc=self.cmd_BLTOUCH_DEBUG_help)

        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)

    def _build_config(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers('Z'):
            stepper.add_to_endstop(self)
    def handle_connect(self):
        self._reset()
    def _reset(self):
        try:
            self.send_cmd_and_verify("reset")
            self.send_cmd_and_verify("pin_up")
        except homing.EndstopError:
            # This is a fatal BLTouch error and should halt the machine
            raise mcu.error("The BLTouch probe is malfunctioning")
        return
    def send_cmd(self, print_time, cmd):
        logging.info("Sending BLTouch command %s" % (cmd, ))
        self.mcu_pwm.set_pwm(print_time, Commands[cmd] / SIGNAL_PERIOD)
    def send_cmd_and_verify(self, cmd):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        self.send_cmd(print_time, cmd)
        self.send_cmd(print_time + MIN_CMD_TIME, None)
        toolhead.dwell(self.pin_move_time)
        toolhead.wait_moves()
        self.mcu_endstop.query_endstop(toolhead.get_last_move_time())
        if self.mcu_endstop.query_endstop_wait():
            logging.info("BLTouch command %s failed" % (cmd,))
            raise homing.EndstopError("BLTouch error when running %s" % (cmd))
    def test_sensor(self):
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.wait_moves()
        self.mcu_endstop.query_endstop(toolhead.get_last_move_time())
        if self.mcu_endstop.query_endstop_wait():
            logging.warning("BLTouch error, trying to reset")
            self._reset()
        if not self.test_sensor_pin:
            return
        print_time = toolhead.get_last_move_time()
        if print_time < self.next_test_time:
            self.next_test_time = print_time + TEST_TIME
            return
        print_time = toolhead.get_last_move_time()
        self.send_cmd(print_time, "pin_up")
        self.send_cmd(print_time + MIN_CMD_TIME, "touch_mode")
        self.send_cmd(print_time + 2*MIN_CMD_TIME, None)
        toolhead.dwell(self.pin_move_time)
        toolhead.wait_moves()
        self.mcu_endstop.query_endstop(toolhead.get_last_move_time())
        if not self.mcu_endstop.query_endstop_wait():
            raise homing.EndstopError("Failed to verify the BLTouch wiring\n."
                "This is not necessarily an error, some clones can't perform this test\n"
                "If that's the case, add test_sensor_pin: False to your configuration.")

        # Reset is not enough to clear the touch_mode, so do a pin_up, followed by reset
        print_time = toolhead.get_last_move_time()
        self.send_cmd(print_time, "pin_up")
        self.send_cmd(print_time + MIN_CMD_TIME, None)
        toolhead.dwell(2 * MIN_CMD_TIME)
        try:
            self.send_cmd_and_verify("reset")
        except homing.EndstopError:
            raise homing.EndstopError("Failed to reset the probe after enabling touch_mode\n"
                                      "Some clones don't supports this, so if that's the case, \n"
                                      "then add test_sensor_pin: False to your configuration.")
        print_time = toolhead.get_last_move_time()
        self.next_test_time = print_time + TEST_TIME
    def home_prepare(self):
        logging.info("BLTouch prepare")
        self.test_sensor()
        try:
            self.send_cmd_and_verify("pin_down")
        except homing.EndstopError:
            # Try to reset in order to move the pin up
            self._reset()
            raise homing.EndstopError("Failed to prepare the BLTouch probe, it's probably too close to the bed")
        self.mcu_endstop.home_prepare()
    def home_finalize(self):
        logging.info("BLTouch finalize")
        try:
            self.send_cmd_and_verify("pin_up")
        except homing.EndstopError:
            self._reset()
            raise homing.EndstopError("An error was detected during the BLTouch probing")
        self.mcu_endstop.home_finalize()
    def home_start(self, print_time, sample_time, sample_count, rest_time):
        rest_time = min(rest_time, ENDSTOP_REST_TIME)
        self.mcu_endstop.home_start(
            print_time, sample_time, sample_count, rest_time)
    def get_position_endstop(self):
        return self.position_endstop
    cmd_BLTOUCH_DEBUG_help = "Send a command to the bltouch for debugging"
    def cmd_BLTOUCH_DEBUG(self, params):
        cmd = self.gcode.get_str('COMMAND', params, None)
        if cmd is None or cmd not in Commands:
            self.gcode.respond_info("BLTouch commands: %s" % (
                ", ".join(sorted([c for c in Commands if c is not None]))))
            return
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        msg = "Sending BLTOUCH_DEBUG COMMAND=%s" % (cmd,)
        self.gcode.respond_info(msg)
        logging.info(msg)
        self.send_cmd(print_time, cmd)
        self.send_cmd(print_time + self.pin_move_time, None)
        toolhead.dwell(self.pin_move_time + MIN_CMD_TIME)

def load_config(config):
    blt = BLTouchEndstopWrapper(config)
    config.get_printer().add_object('probe', probe.PrinterProbe(config, blt))
    return blt
