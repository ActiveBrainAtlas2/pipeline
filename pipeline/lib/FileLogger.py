import os, sys
from os import environ
from pathlib import Path
import logging
from datetime import datetime

class FileLogger:
    def __init__(self, LOGFILE_PATH):
        """
        -SET CONFIG FOR LOGGING TO FILE; ABILITY TO OUTPUT TO STD OUTPUT AND FILE

        """

        LOGFILE = os.path.join(LOGFILE_PATH, "pipeline-process.log")

        # SET ENV FOR OTHER [NON-PIPELINE] MODULES
        if environ.get("LOGFILE_PATH") is None:
            os.environ["LOGFILE_PATH"] = LOGFILE_PATH

        logger = logging.getLogger(__name__)
        logger.setLevel(logging.DEBUG) #THRESHOLD FOR LOGGER
        formatter = logging.Formatter("%(message)s")

        # 'FOR LOOP' REMOVES DUAL LOGGING TO CONSOLE + FILE
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        # Create file handler for INFO and up (INFO, WARNING, ERROR, CRITICAL)
        fh = logging.FileHandler(LOGFILE)
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        # CONSOLE + LOG FILE
        # logger = logging.getLogger(__name__)
        # logger.setLevel(logging.DEBUG)
        # fh = logging.FileHandler(LOGFILE)
        # formatter = logging.Formatter("%(message)s")
        # fh.setFormatter(formatter)
        # logger.addHandler(fh)

        self.filelogger = logger


    def logevent(self, msg: str):
        timestamp = datetime.today().strftime("%Y-%m-%d %H:%M:%S")
        self.filelogger.info(f"{timestamp} - {msg}")
        return timestamp
