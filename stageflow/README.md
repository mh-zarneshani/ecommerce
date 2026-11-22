# Stageflow dashboard

Run the existing Python app with its PostgreSQL database. Open
http://127.0.0.1:8765/stageflow/ (use the configured port if different).
The original sales desk at `/` handles data import, workbook review, and
synthetic demo setup. Start the synthetic demo there to try an approval, or
import the workbook and run a review for the cutoff you want to inspect.

Stageflow uses the existing same-origin session and API. Reporting and case
filters use backend account IDs and the selected cutoff. Approval requires a
validated draft and server permission. After an uncertain result, refresh the
case to check whether the referral was recorded.

The public baseline omits the original frontend, test suite, and SQL migrations
required by the backend. Use the teammate's complete checkout for setup and
database-backed verification.
