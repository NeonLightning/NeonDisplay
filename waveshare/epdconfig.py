# /usr/local/lib/python3.11/dist-packages/waveshare_epd/epdconfig.py
import logging
import sys
import time
from periphery import GPIO, SPI

logger = logging.getLogger(__name__)

# Module-level constants (driver reads these)
RST_PIN  = ("/dev/gpiochip0", 17)
DC_PIN   = ("/dev/gpiochip0", 25)
CS_PIN   = ("/dev/gpiochip0", 8)
BUSY_PIN = ("/dev/gpiochip0", 24)

class RaspberryPi:
    # Class-level attributes (used by __init__)
    RST_PIN  = ("/dev/gpiochip0", 17)
    DC_PIN   = ("/dev/gpiochip0", 25)
    CS_PIN   = ("/dev/gpiochip0", 8)
    BUSY_PIN = ("/dev/gpiochip0", 24)
    CHUNK_SIZE = 4096

    def __init__(self):
        self.GPIO_RST_PIN = GPIO(*self.RST_PIN, "out")
        self.GPIO_DC_PIN  = GPIO(*self.DC_PIN, "out")
        self.GPIO_BUSY_PIN = GPIO(*self.BUSY_PIN, "in")
        self.SPI = SPI("/dev/spidev0.0", 0, 4_000_000)

    def __del__(self):
        """Cleanup GPIO and SPI resources when object is destroyed"""
        try:
            logger.debug("Cleaning up GPIO and SPI resources...")
            self.module_exit()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def _chunked_transfer(self, data):
        """Transfer data in chunks to prevent buffer overflows"""
        if isinstance(data, list):
            data = bytes(data)
        
        for i in range(0, len(data), self.CHUNK_SIZE):
            chunk = data[i:i + self.CHUNK_SIZE]
            self.SPI.transfer(chunk)

    def digital_write(self, pin, value):
        if pin == self.RST_PIN:
            self.GPIO_RST_PIN.write(bool(value))
        elif pin == self.DC_PIN:
            self.GPIO_DC_PIN.write(bool(value))

    def digital_read(self, pin):
        if pin == self.BUSY_PIN:
            return self.GPIO_BUSY_PIN.read()
        return 0

    def delay_ms(self, delaytime):
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data):
        self._chunked_transfer(data)

    def spi_writebyte2(self, data):
        self._chunked_transfer(data)

    def module_init(self):
        return 0

    def module_exit(self):
        logger.debug("spi end")
        try:
            self.SPI.close()
        except Exception:
            pass

        # Only close pins, do NOT write
        try:
            self.GPIO_RST_PIN.close()
        except Exception:
            pass
        try:
            self.GPIO_DC_PIN.close()
        except Exception:
            pass
        try:
            self.GPIO_BUSY_PIN.close()
        except Exception:
            pass

        logger.debug("Module cleanup complete")


implementation = RaspberryPi()

for func in [x for x in dir(implementation) if not x.startswith('_')]:
    setattr(sys.modules[__name__], func, getattr(implementation, func))

### END OF FILE ###
