# Ecronx Technologies — Manpower & Attendance

This project keeps the existing Ecronx Manpower website, admin panel, services, gallery, contact details and enquiry form, and adds an integrated employee attendance portal. The static HTML/CSS/JavaScript frontend is in `frontend/`; the Express API and JSON-file persistence are in `backend/`.

## Requirements and run on Windows

- Node.js 18 or newer.
- From the project root, install the frontend and backend dependencies:

```sh
npm install
```

- Configure the administrator credentials and start both local servers from the project root:

```bat
set ADMIN_USER=admin
set ADMIN_PASS=replace-this-with-a-long-unique-password
set ATTENDANCE_TIME_ZONE=Asia/Kolkata
npm start
```

Alternatively, in PowerShell:

```powershell
$env:ADMIN_USER = "admin"
$env:ADMIN_PASS = "replace-this-with-a-long-unique-password"
$env:ATTENDANCE_TIME_ZONE = "Asia/Kolkata"
npm start
```

Keep the terminal open and visit:

- Website: `http://localhost:3000/`
- Attendance: `http://localhost:3000/attendance`
- Backend API: `http://localhost:3000/`
- Existing content admin: click **Admin access** in the website footer.

The same `ADMIN_USER` and `ADMIN_PASS` credentials are used for the existing website admin and the attendance dashboard. Admin login is disabled until these environment variables are configured; there is no built-in demo password. Set a strong, unique password and do not share it. The environment variables must be configured again in each new terminal session, or set persistently using Windows Environment Variables. Never commit a real password to the project or share it with employees.

## Employee access and first admin setup

1. Sign in to the Attendance page using the **Administrator** tab and the configured admin credentials. This reuses the existing admin authentication endpoint; all attendance admin APIs also verify the admin role on the server.
2. In **Add client / site**, create any client and site details needed for allocation.
3. In **Add employee**, create each employee's name, unique username, initial password (at least 12 characters), and optional site assignment. Generate a distinct initial password and deliver it privately to that employee. No employee accounts or attendance records are pre-seeded.
4. Employees visit `/attendance`, choose **Employee**, and sign in with the credentials provided by the admin. They can see only their own history. Use **Secure logout** when finished.

Employee passwords are salted and hashed with Node.js `scrypt`; plaintext passwords are not written to JSON. Admin and employee sessions expire after 12 hours and are held in server memory, not browser storage. Restarting the server invalidates active sessions.

## Check-in, check-out and privacy

The browser requests one high-accuracy location fix only after an employee presses **Check in** or **Check out**. A successful request stores server time, latitude, longitude, reported accuracy and an address only if one is supplied by the browser. Browser geolocation does not ordinarily provide a street address, so coordinates and a map link are available instead. There is no background or continuous tracking. A failed/denied location request is reported with retry guidance, and the employee can retry the action.

GPS requires a secure browser context: `http://localhost` works for local testing; access from other computers requires HTTPS. Grant location permission in the browser and enable device location services. Attendance records are dated using `ATTENDANCE_TIME_ZONE` (default `Asia/Kolkata`). Check-in/out duplicates are blocked by the server. Working hours are calculated from stored timestamps; overtime is shown after eight hours. Corrections need admin approval and manually corrected times are clearly marked as having no GPS fix.

## Admin attendance dashboard

The dashboard includes active employee, present, absent, leave and currently checked-in totals; date, employee, date-range and month filters; check-in/out timestamps, GPS accuracy and map links; working hours and overtime; client/site allocation; employee account creation; leave marking; and review/approval/rejection of employee time-correction requests.

**Download Weekly Backup** exports the selected date range as a JSON backup. You can change the date range before download. CSV (Excel-compatible UTF-8 with BOM) and PDF report buttons use that same range. Filenames include both date boundaries. Downloading never deletes or changes attendance history. The dashboard reminds the admin when no backup has been recorded and shows the latest downloaded backup date/range.

Backups include employee account hashes and salts so employee accounts can be restored; treat JSON backups as sensitive and keep them in a private, access-controlled location.

### Restore from a JSON backup

1. Stop the server and make a separate copy of the whole current `backend/data` folder.
2. Open the admin-only JSON backup in a trusted local editor. The backup has `employees`, `attendance`, `sites` and `correctionRequests` arrays.
3. Replace the contents of `backend/data/attendance-employees.json`, `backend/data/attendance-records.json`, `backend/data/attendance-sites.json` and `backend/data/attendance-corrections.json` with the corresponding JSON arrays from the backup. Each file must contain a JSON array. Leave `backend/data/content.json` and unrelated website data unchanged.
4. Start the server again and verify accounts and records in the attendance dashboard.

The backup contains records only for its selected date range, while employee/site data is included as a whole. For full-history recovery, choose a date range spanning all required attendance and correction dates. Keep the backup and its account hashes private.

## Local data files

Attendance data is kept on the computer running the Node.js server:

- `backend/data/attendance-employees.json` — employee account metadata and scrypt password hashes.
- `backend/data/attendance-records.json` — attendance, timestamps and check-in/out GPS fixes.
- `backend/data/attendance-sites.json` — client and site details.
- `backend/data/attendance-corrections.json` — submitted and reviewed correction requests.
- `backend/data/attendance-backups.json` — date, range and format of completed backup downloads.

Files are created automatically as empty JSON arrays the first time the API is used. Mutations are serialized to avoid concurrent JSON updates overwriting one another, and files are atomically replaced. Keep this project folder on a reliable local disk, restrict Windows folder permissions, and include these files in your normal secure backup plan. Do not place sensitive files in a public web directory.

## Existing website features

The existing responsive marketing pages, logo, images, contact information, editable services and gallery, enquiries and website admin remain in place. The new **Attendance** navigation item links to the integrated portal. Website admin uploads remain in `backend/uploads/`; enquiries continue to be stored in `backend/data/content.json`.

## Screenshots

The ZIP includes captures of the live updated company homepage (`screenshots/homepage-updated.png`) and the authenticated attendance admin dashboard (`screenshots/attendance-dashboard.png`).
