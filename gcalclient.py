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


    def upsert_events(
        self,
        calendar_id: str,
        orders: list[dict],
        body_builder,  # callable: order -> event body dict (or None to skip)
        days_before: int = 365,
        days_after: int = 365,
        tz_name: str = "America/Los_Angeles",
    ) -> list[dict]:
        """
        Upsert events based on a stable key in extendedProperties.private.order_key.
        - `body_builder(order)` must return a full Google Calendar event body dict
          including `extendedProperties.private.order_key`. Return None to skip.
        """
        # Fetch existing events in the window
        existing = self.get_all_events_in_range(
            calendar_id=calendar_id,
            days_before=days_before,
            days_after=days_after,
            tz_name=tz_name,
        )

        # Index by our stable key
        by_key: dict[str, dict] = {}
        for ev in existing:
            ext = ev.get("extendedProperties", {}).get("private", {})
            k = ext.get("order_key")
            if k:
                by_key[str(k)] = ev

        # Upsert loop
        changed: list[dict] = []
        for order in orders:
            body = body_builder(order)
            if not body:
                continue

            key = body.get("extendedProperties", {}).get("private", {}).get("order_key")
            if not key:
                # Safe-guard: body_builder must provide the key
                continue

            if key not in by_key:
                created = self.service.events().insert(calendarId=calendar_id, body=body).execute()
                print(f"Created: {key} → {created.get('htmlLink')}")
                changed.append(created)
            else:
                ev_id = by_key[key]["id"]
                updated = self.service.events().update(calendarId=calendar_id, eventId=ev_id, body=body).execute()
                print(f"Updated: {key} → {updated.get('htmlLink')}")
                changed.append(updated)

        return changed
