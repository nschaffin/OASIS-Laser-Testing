import serial
import serial.tools.list_ports
import time
import threading as thread


class Laser:
    def __init__(self, pulseMode = 0, repRate = 10, burstCount = 10000, diodeCurrent = .1, energyMode = 0, pulseWidth = 10, diodeTrigger = 0):
        self.__ser = serial.Serial()
        self.pulseMode = pulseMode # NOTE: Pulse mode 0 = continuous is actually implemented as 2 = burst mode in this code.
        self.repRate = repRate
        self.burstCount = burstCount
        self.diodeCurrent = diodeCurrent
        self.energyMode = energyMode
        self.pulseWidth = pulseWidth
        self.diodeTrigger = diodeTrigger
        self.burstDuration = burstCount/repRate

        self.__kicker_control = False  # False = off, True = On. Controls kicker for shots longer than 2 seconds
        self.__startup = True
        self.__threads = []
        self.__lock = thread.Lock() # this lock will be acquired every time the serial port is accessed.
        self.__device_address = "LA"
        self.update_settings()

    def editConstants(self, pulseMode = 0, repRate = 10, burstCount = 10000, diodeCurrent = .1, energyMode = 0, pulseWidth = 10,  diodeTrigger = 0):
        """
        Update the laser settings

        Parameters
        ----------
        pulseMode : int
            0 = continuous (actually implemented as burst mode), 1 = single shot, 2 = burst mode in this code.
        repRate : float
            0 = Rate of laser firing in Hz (1 to 30)
        burstCount : int
            number of shots to fire (if pulse mode is 0 or 2)
        diodeCurrent : float
            Current to diode (see laser ATP spec sheet which comes with the laser for  optimal settings)
        energyMode : int
            0 = manual mode, 1 = low power, 2 = high power
        pulseWidth : float
            sets the diode pulse width (see laser ATP spec sheet which comes with laser for optimal settigns)
        diodeTrigger : int
            0 = internal, 1 = external
        """
        self.pulseMode = pulseMode
        self.repRate = repRate
        self.burstCount = burstCount
        self.diodeCurrent = diodeCurrent
        self.energyMode = energyMode
        self.pulseWidth = pulseWidth
        self.diodeTrigger = diodeTrigger
        self.burstDuration = burstCount/repRate
        self.update_settings()

    def __kicker(self):  # queries for status every second in order to kick the laser's WDT on shots >= 2s
        """Queries for status every second in order to kick the laser's WDT on shots >= 2s"""
        while True:
            if self.__kicker_control:
                self.__ser.write('SS?')
            time.sleep(1)

    def __send_command(self, cmd, timeout=self.__response_timeout):
        """
        Sends command to laser

        Parameters
        ----------
        cmd : string
            This contains the ASCII of the command to be sent. Should not include the prefix, address, delimiter, or terminator
            
        Returns
        ----------
        response : bytes
            The binary response received by the laser. Includes the '\r' terminator. May be None is the read timedout.
        """
        if len(cmd) == 0:
            return
        
        # Form the complete command string, in order this is: prefix, address, delimiter, command, and terminator
        cmd_complete = ";" + self.__device_address + ":" + cmd + "\r"
        
        with self.__lock: # make sure we're the only ones on the serial line
            self.__ser.write(cmd_complete.encode("ascii")) # write the complete command to the serial device
            time.sleep(0.01)
            response = self.__ser.read_until(expected="\r") # laser returns with <CR> = \r

        return response

    def connect(self, port_number, baud_rate=115200, timeout=1, parity=None):
        """
        Sets up connection between flight computer and laser

        Parameters
        ----------
        port_number : int
            This is the port number for the laser

        baud_rate : int
            Bits per second on serial connection

        timeout : int
            A buffer for if connection is not established

        """
        with self.__lock:
            if port_number not in serial.tools.list_ports.comports():
                raise ValueError(f"Error: port {port_number} is not available")
            self.__ser = serial.Serial(port=port_number)
            if baud_rate and isinstance(baud_rate, int):
                self.__ser.baudrate = baud_rate
            else:
                raise ValueError('Error: baud_rate parameter must be an integer')
            if timeout and isinstance(timeout, int):
                self.__ser.timeout = timeout
            else:
                raise ValueError('Error: timeout parameter must be an integer')
            if not parity or parity == 'none':
                self.__ser.parity = serial.PARITY_NONE
            elif parity == 'even':
                self.__ser.parity = serial.PARITY_EVEN
            elif parity == 'odd':
                self.__ser.parity = serial.PARITY_ODD
            elif parity == 'mark':
                self.__ser.parity = serial.PARITY_MARK
            elif parity == 'space':
                self.__ser.parity = serial.PARITY_SPACE
            else:
                raise ValueError("Error: parity must be None, \'none\', \'even\', \'odd\', \'mark\', \'space\'")
            if self.__startup:  # start kicking the laser's WDT
                t = thread.Thread(target=self.__kicker())
                self.__threads.append(t)
                t.start()
                self.__startup = False

    # Added: changed lock structure
    def fire_laser(self):
        """
            Sends commands to laser to have it fire
        """
        self.__send_command('FL 1')
        response = self.__send_command('SS?')

        if response != '3075\r':
            self.__send_command('FL 0')  # aborts if laser fails to fire
            raise RuntimeError('Laser Failed to Fire')
        else:
            if self.burstDuration >= 2:
                self.__kicker_control = True
            time.sleep(self.burstDuration)
            self.__send_command('FL 0')

    def get_status(self):
        """
        Obtains the status of the laser
        Returns
        _______
        status : bytes
            Returns the int value of the status of the laser status in bytes string
                (Sum of 2^13 = High power mode; 2^12 = Low power mode, 2^11 = Ready to fire, 2^10 = Ready to enable
                2^9 = Power failure, 2^8 = Electrical over temp, 2^7 = Resonator over temp, 2^6 = External interlock,
                2^3 = diode external trigger, 2^1 = laser active, 2^0 = laser enabled)
        """
        return self.__send_command('SS?')
            

    def check_armed(self):
        """
        Checks if the laser is armed
        Returns
        _______
        armed : boolean
            the lasr is armed
        """
        response = self.__send_command('EN?')
        if response and len(response) == 2:
            return response[1] == b'1'

    # Added: FET temperature
    def fet_temp_check(self):
        """
        Checks the FET temperature the laser

        Returns
        _______
        fet : bytes
            Returns the float value of the FET temperature in bytes string.
        """
        response = self.__send_command('FT?')
        return response[:-4]

    # Added: Resonator temperature
    def resonator_temp_check(self):
        """
        Checks the resonator temperature the laser

        Returns
        _______
        resonator_temp : bytes
            Returns the float value of the resonator temperature in bytes string.
        """
        response - self.__send_command('TR?')
        return response[:-4]

    # Added: FET voltage
    def fet_voltage_check(self):
        """
        Checks the FET voltage of the laser

        Returns
        _______
        fet_voltage : bytes
            Returns the float value of the FET voltage in bytes string.
        """
        response = self.__send_command('FV?')
        return response[:-4]
            
    # Added: Diode Trigger Mode
    def set_trigger_mode(self, mode):
        """
        Sets the trigger mode of the laser. 0 = Internal/software. 1 - External trigger
        """
        response = self.__send_command('FV?')
        return response[:-4]

    def diode_current_check(self):
        """
        Checks current to diode of the laser

        Returns
        -------
        diode_current : bytes
            Returns the float value of the diode current in bytes string.
        """
        response = self.__send_command('IM?')
        return response[:-4]

    # Added: emergency stop
    def emergency_stop(self):
        """Immediately sends command to laser to stop firing (no lock)"""
        self.__send_command('FL 0')

    def arm(self):
        """Sends command to laser to arm"""
        self.__send_command('EN 1')

    def disarm(self):
        """Sends command to laser to disarm"""
        self.__send_command('EN 0')

    def update_settings(self):
        # cmd format, ignore brackets => ;[Address]:[Command String][Parameters]\r
        """Updates laser settings"""
        cmd_strings = list()
        cmd_strings.append('PM ' + str(self.pulseMode))
        cmd_strings.append('RR ' + str(self.repRate))
        cmd_strings.append('BC ' + str(self.pulseMode))
        cmd_strings.append('DC ' + str(self.diodeCurrent))
        cmd_strings.append('EM ' + str(self.energyMode))
        cmd_strings.append('PM ' + str(self.pulseMode))
        cmd_strings.append('DW ' + str(self.pulseWidth))
        cmd_strings.append('DT ' + str(self.pulseMode))

        for i in cmd_strings:
            self.__send_command(i)


def list_available_ports():
    return serial.tools.list_ports.comports()
