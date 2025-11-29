import logging
import os
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql
import pytz
from datetime import datetime

class Logger:
    def __init__(self):
        load_dotenv()
        level = os.getenv("LOG_LEVEL", "INFO").upper()
        self.logger = logging.getLogger("notifier")
        self.logger.setLevel(level)
        
        self.file_handler = None
        self.stream_handler = None

        if not self.logger.handlers:
            # File handler
            self.file_handler = logging.FileHandler("notifier.log")
            self.file_handler.setLevel(level)
            self.formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(filename)s: %(levelname)s - %(message)s"
            )
            self.file_handler.setFormatter(self.formatter)
            self.logger.addHandler(self.file_handler)

            # Stream handler (for terminal output)
            self.stream_handler = logging.StreamHandler()
            self.stream_handler.setLevel(level)
            self.stream_handler.setFormatter(self.formatter)
            self.logger.addHandler(self.stream_handler)

            self.logger.info("==========================================================================")
            self.logger.info("START")

            self.logger.info("Logger initialized")
            self.logger.debug("Debugging enabled")
            self.logger.info("Info enabled")
            self.logger.warning("Warning enabled")
            self.logger.error("Error enabled")
            self.logger.critical("Critical enabled")

    def console(self, message):
        self.logger.info(message)
        if self.file_handler:
            self.file_handler.flush()

    def info(self, message):
        logDB("info", message)
        self.logger.info(message)
        if self.file_handler:
            self.file_handler.flush()

    def success(self, message):
        logDB("success", message)
        self.logger.info(message)
        if self.file_handler:
            self.file_handler.flush()

    def debug(self, message):
        self.logger.debug(message)
        if self.file_handler:
            self.file_handler.flush()

    def warning(self, message):
        self.logger.warning(message)
        if self.file_handler:
            self.file_handler.flush()

    def error(self, message):
        logDB("error", message)
        self.logger.error(message)
        if self.file_handler:
            self.file_handler.flush()

    def critical(self, message):
        self.logger.critical(message)
        if self.file_handler:
            self.file_handler.flush()

    def close(self):
        if self.file_handler:
            self.file_handler.close()
        logging.shutdown()
        self.logger.info("Logger closed")
        self.logger.debug("Debugging disabled")
        self.logger.info("Info disabled")
        self.logger.warning("Warning disabled")
        self.logger.error("Error disabled")
        self.logger.critical("Critical disabled")
        self.logger.info("END")
        self.logger.info("==========================================================================")


class NotifierDB():
    def __init__(self):
        load_dotenv(override=True)
        # Inizializzatore della connessione
        HOSTNAME = os.getenv('DB_HOST')
        DATABASE = os.getenv('DB_NAME')
        USERNAME = os.getenv('DB_USER')
        PASSWORD = os.getenv('DB_PASSWORD')
        PORT = os.getenv('DB_PORT')
        if(os.getenv('ENVIROMENT') == "backup"):
            self.TABLE = "logs_backup_notifier"
        else:
            self.TABLE = "logs_notifier"

        try:
            self.connection = psycopg2.connect(
                host=HOSTNAME,
                dbname=DATABASE,
                user=USERNAME,
                password=PASSWORD,
                port=PORT,
            )
        except Exception:
            NotifierDB()

        self.cursor = self.connection.cursor()

    def close_connection(self) -> None:
        """Closes the connection to the database."""
        self.connection.close()
        return
    
def logDB(type: str, message: str = None) -> None:
    """
    Log in db
    """

    DB = NotifierDB()
    DB.cursor.execute(sql.SQL("""
        INSERT INTO {} (type, message, timestamp)
        VALUES (%s, %s, %s)
    """).format(sql.Identifier(DB.TABLE)), (type, message, datetime.now(pytz.timezone('Europe/Rome'))))
    DB.connection.commit()
    DB.close_connection()
    return

def clearDBLog():
    # if last log is success then clear all logs except success or error
    DB = NotifierDB()
    DB.cursor.execute(sql.SQL("SELECT * FROM {} ORDER BY timestamp DESC LIMIT 1").format(
    sql.Identifier(DB.TABLE)))
    response = DB.cursor.fetchall()
    DB.connection.commit()
    if response[0][1] == "success":
        DB.cursor.execute(sql.SQL("DELETE FROM {} WHERE type != 'success' AND type != 'error'").format(
        sql.Identifier(DB.TABLE)))
        DB.connection.commit()
    DB.close_connection()
    return