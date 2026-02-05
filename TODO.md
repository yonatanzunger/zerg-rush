# TODOs that still need to happen:

## Major categories

1. Finish the VM startup logic: get it to the point where it actually starts an openclaw in a healthy state and you can talk to it.
   - Verify that the new shorter script works, and start adding real permissions to it
   - Get the server started up and wire it through to the chat UI in the app
   - Make sure the "hatch" flow works there
1. Implement save / restore state: this is really about grabbing the stuff in .openclaw usefully.
   - Also make sure we autosave immediately after hatching
1. Ensure that the agent really can usefully transfer files using the storage bucket mechanism, so that if you ask it "make me X and stick the results here" it works.
1. Validate that the Azure implementation works (I've only really been testing GCP so far) and also add AWS.
1. Various cleanups.
   - Add expandos to log view so you can read what's in there
   - Make alembic operations idempotent in case they fail partway through
   - Fix hanging on error during RPCs
   - Make startups cleaner: have it be user-visible on the app once the startup script finishes (not just once the VM is up), and maybe even mirror the startup script logs into the dashboard.
   - Add link to storage bucket to the UI
1. Have it do a security review, using OWASP etc!
   - Think through the token encryption logic: Do we need to be using a vTPM or something similar?
   - Prevent public access in bucket? Right now you can mark things as world-readable and I'm not sure that's wise.

## Things requiring some thinking

- What else can we do to monitor the system? MDE or the like?
- Do we need _central_ visibility across MSFT? i.e., in enterprise use, do we want this to link upstream?
