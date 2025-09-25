# Setup
1) Create venv and install:
   ```
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
2) Set env vars:
   ```
   export TG_BOT_TOKEN="YOUR_TOKEN"
   export OWNER_ID="7040724501"
   ```
3) Run:
   ```
   python bot.py
   ```
4) Owner: /start → Owner panel. Send a DOCX with sections:
   - Savollar:
   - Javoblar:
   - Izohlar:
   Then go to Tests to see it listed.
5) Student: /start → list active tests (send test_id to begin once activated).
