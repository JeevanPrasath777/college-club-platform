# Campus Clubhouse

A college club platform for event planning, approval, registrations, attendance, On-Duty (OD) requests, certificates, badges, and club communication.

## Technology

- Frontend: HTML, CSS, and vanilla JavaScript
- Backend: FastAPI and SQLAlchemy
- Database: SQLite with foreign-key enforcement
- Authentication: email/password with JWT

## Run on Windows

Open two terminals in VS Code and keep both servers running.

### Terminal 1: Backend

```powershell
cd "C:\Users\srtth\OneDrive\Desktop\college-club-platform\backend"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python seed.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

If `.env` already exists, keep it and do not overwrite your configured secret. The seed script is safe to rerun: it adds missing demo users, clubs, events, and timetable data without replacing existing accounts or passwords. API documentation is at <http://127.0.0.1:8000/docs>.

### Terminal 2: Frontend

```powershell
cd "C:\Users\srtth\OneDrive\Desktop\college-club-platform\frontend"
python -m http.server 5173 --bind 127.0.0.1
```

Open <http://127.0.0.1:5173>. Stop either server with Ctrl+C.

### If clubs or events are missing

In a separate VS Code terminal, run:

```powershell
cd "C:\Users\srtth\OneDrive\Desktop\college-club-platform\backend"
.\.venv\Scripts\Activate.ps1
python seed.py
```

Then sign out and back in, or hard-refresh the browser with `Ctrl+F5`. Confirm the backend terminal is still running and `http://127.0.0.1:8000/api/health` shows `{"ok":true}`.

### Demo accounts

| Role | Email | Password | Student RA Number |
| --- | --- | --- | --- |
| Super Admin | superadmin@college.edu | SuperAdmin@123 | — |
| Admin | admin@college.edu | Admin@123 | — |
| Faculty | faculty@college.edu | Faculty@123 | — |
| Faculty | faculty2@college.edu | Faculty@123 | — |
| Club Admin | clubadmin@college.edu | ClubAdmin@123 | — |
| Student | student@college.edu | Student@123 | RA2411001001001 |
| Student | student2@college.edu | Student@123 | RA2411001001002 |

Fresh seed IDs are also shown in Admin tools. Do not rely on numeric IDs if the database was created earlier.

### Live attendance demo

1. Sign in as `clubadmin@college.edu` and open **Attendance**.
2. Select **Campus Welcome Mixer** and generate the check-in code. It expires after 10 minutes.
3. Sign in as `student2@college.edu`, open **Attendance**, select the same event, and enter the code. This demo student is pre-registered for the event.

## Main workflows

- Admin creates a club and assigns a Club Admin and Faculty Coordinator.
- Club Admin submits an event; only that club's assigned Faculty Coordinator or the Super Admin can approve it.
- Students can register only for approved events. Registration is limited by capacity and duplicates are rejected.
- While an event is running, an organizer can generate a short-lived check-in code; registered students use it to record attendance.
- Students request OD only for their own approved event registration. The request goes to their Class Mentor and freezes the affected period details.
- Super Admin creates and activates college period structures. Event creation previews overlapping class periods.
- Organizers record attendance. Certificates require a completed event and confirmed attendance; each PDF has a verification ID.
- Faculty and Club Admins can message one another in the same club; event-linked conversations are supported.

## Documentation and coverage

See [the hackathon feature and workflow guide](docs/hackathon-guide.md) for the database overview, workflow diagrams, implemented coverage, and remaining limitations.

## Local checks

```powershell
cd "C:\Users\srtth\OneDrive\Desktop\college-club-platform\backend"
.\.venv\Scripts\Activate.ps1
pytest -q
```

Use only demo data in a submission. Keep `.env` private; distribute `.env.example` with placeholder values instead. Google Sign-In still needs an OAuth client setup and is listed as incomplete in the coverage guide.
