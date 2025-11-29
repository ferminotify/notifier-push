# Push Notifier
Push Notifier checks every x minutes for new events and sends push notifications to users.
## Usage
1. Configure ```.env``` file with your settings.
2. Set up a virtual environment and install dependencies in ```requirements.txt```.
3. Set up a scheduler (e.g., cron job) to run the script periodically:
```bash
*/5 * * * * /path/to/venv/bin/python /path/to/main.py
```
## Configuration
- `DB_HOST`: Database host address.
- `DB_PORT`: Database port number.
- `DB_NAME`: Name of the database.
- `DB_USER`: Database username.
- `DB_PASSWORD`: Database password.
- `ENVIRONMENT`: Application environment (e.g., production, development).
- `LOG_LEVEL`: Logging level (e.g., INFO, DEBUG).
- `TZ`: Timezone for the application.