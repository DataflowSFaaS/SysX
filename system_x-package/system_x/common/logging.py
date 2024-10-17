from aiologger import Logger
from aiologger.levels import LogLevel
from aiologger.formatters.base import Formatter

logging = Logger.with_default_handlers(name='system_x',
                                       level=LogLevel.WARNING,
                                       formatter=Formatter(fmt='%(asctime)s.%(msecs)03d %(levelname)s:\t%(message)s'))
