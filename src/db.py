import os
import time
from dotenv import load_dotenv
import psycopg2
from src.logger import Logger
logger = Logger()

"""
Summary of all the operations involving the database.
Tables involved:
- subscribers
- push
- push_sent

push_sent
CREATE TABLE push_sent (
    sub_id     INTEGER NOT NULL,
    uid        VARCHAR NOT NULL,
    device_id  TEXT NOT NULL,
    CONSTRAINT fk_push_sent_subscribers
        FOREIGN KEY (sub_id)
        REFERENCES subscribers(id)
        ON DELETE CASCADE
);
"""

ssl_cert_path = 'cert.pem'

class NotifierDB():
	"""This class is used to connect to the database and perform
	operations on it regarding telegram and emails.

	In production, only the operations needed to request data will be used.
	The insertion of data will be done on the website.

	All the methods in this class don't close the connection to the database,
	in fact there are present specific functions named exactly alike outside
	of the class, that close the connection.

	Attributes:
		connection (psycopg2.extensions.connection): connection to the database.
		cursor (psycopg2.extensions.cursor): cursor to the database.
	"""

	def __init__(self):
		load_dotenv(override=True)
		# Inizializzatore della connessione
		HOSTNAME = os.getenv('DB_HOST')
		DATABASE = os.getenv('DB_NAME')
		USERNAME = os.getenv('DB_USER')
		PASSWORD = os.getenv('DB_PASSWORD')
		PORT = os.getenv('DB_PORT')
		try:
			self.connection = psycopg2.connect(
				host=HOSTNAME,
				dbname=DATABASE,
				user=USERNAME,
				password=PASSWORD,
				port=PORT,
				#sslmode='verify-full',
        			#sslrootcert=ssl_cert_path
			)
			logger.debug("Database connection established.")
		except Exception as e:
			logger.error(f"Error connecting to the database: {e}")
			time.sleep(30)
			NotifierDB()

		self.cursor = self.connection.cursor()

	def close_connection(self) -> None:
		"""Closes the connection to the database."""
		self.connection.close()
		logger.debug("Database connection closed.")
		return

	def get_subscribers_push(self) -> list[tuple]:
		"""
		Returns:
			list: list of tuples containing subscribers that have push notifications enabled.
		"""
		self.cursor.execute("""
            SELECT
                p.sub_id AS id,
                p.endpoint,
                p.send_push_with_notifications,
				p.device_id,
                s.tags AS keywords,
                s.notification_day_before,
                s.notification_time,
                s.email
            FROM push AS p
            JOIN subscribers AS s ON p.sub_id = s.id;
        """)
		fetched_subscribers = self.cursor.fetchall()
		self.connection.commit()

		column_names = [desc[0] for desc in self.cursor.description]
		fetched_subscribers = [dict(zip(column_names, row)) for row in fetched_subscribers]
		logger.debug("Fetched all subscribers from the database.")
		
		return fetched_subscribers

	def get_all_sent_push_id(self, user_id: int, device_id: str) -> list[str]:
		"""Gets all the event UIDs that have been sent to a specific user device.

		Args:
			user_id (int): id of the user.
			device_id (str): id of the device.

		Returns:
			list: list of event UIDs sent to this specific device.
		"""
		self.cursor.execute(
			"SELECT uid FROM push_sent WHERE sub_id = %s AND device_id = %s",
			(user_id, device_id)
		)
		response = self.cursor.fetchall()
		self.connection.commit()
		logger.debug(f"Fetched all sent notification IDs for user {user_id}, device {device_id}.")

		# Flatten uid list
		response = [i[0] for i in response]

		return response

	def store_push_sent(self, user_id: int, event_id: str, device_id: str) -> None:
		"""Store the notification in the database.

		Args:
			user_id (int): id of the user.
			event_id (int): id of the event.
		"""
		pattern = "INSERT INTO push_sent (sub_id, uid, device_id) VALUES (%s, %s, %s)"
		self.cursor.execute(pattern, (user_id, event_id, device_id))
		self.connection.commit()
		logger.debug(f"Stored event ID {event_id} for user ID {user_id}.")
		
		return