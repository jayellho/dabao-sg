import datetime
from zoneinfo import ZoneInfo, available_timezones
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarClient:
    def __init__(self, credentials_path="credentials.json", token_path="token.json", scopes=None):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes or SCOPES
        self.creds = None
        self.service = None
        self._authenticate()
        self._build_service()

    def _authenticate(self):
        creds = None
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, self.scopes)
                creds = flow.run_local_server(port=0)
            with open(self.token_path, "w") as token:
                token.write(creds.to_json())
        self.creds = creds

    def _build_service(self):
        self.service = build("calendar", "v3", credentials=self.creds)

    def get_all_events_in_range(self, calendar_id="primary",
                       days_before=None, days_after=None, max_results_per_page=2500,
                       tz_name="America/Los_Angeles"):
        """
        Fetch events from (now - days_before) to (now + days_after).
        - days_before: int days before now (default 365 if None)
        - days_after : int days after now (default 365 if None)
        - tz_name    : IANA timezone; if invalid, prints available zones and uses default.
        """
        before_days = 365 if days_before is None else int(days_before)
        after_days  = 365 if days_after  is None else int(days_after)
        if before_days < 0 or after_days < 0:
            raise ValueError("time_min/time_max (days) must be >= 0")

        default_tz = "America/Los_Angeles"
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            zones = ", ".join(sorted(available_timezones()))
            print(f"Invalid timezone '{tz_name}'. Using default '{default_tz}'.")
            print(f"Available timezones: {zones}")
            tz = ZoneInfo(default_tz)

        now = datetime.datetime.now(tz)
        print(f"Using timezone: {tz.key}")

        start_dt = now - datetime.timedelta(days=before_days)
        end_dt   = now + datetime.timedelta(days=after_days)

        tmin = start_dt.isoformat()
        tmax = end_dt.isoformat()

        events, page_token = [], None
        while True:
            res = self.service.events().list(
                calendarId=calendar_id,
                singleEvents=True,
                orderBy="startTime",
                timeMin=tmin,
                timeMax=tmax,
                maxResults=max_results_per_page,
                pageToken=page_token,
            ).execute()
            events.extend(res.get("items", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return events
