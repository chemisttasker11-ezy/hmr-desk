# Developer tools (test builds only)

## Synthetic visit-stage patient

`engine_main --dev-seed-visit` adds one synthetic patient ("DEV SEED Synthetic Patient N") whose visit is recorded, with a confirmed medicine list and the interaction check done. The next step is **Start report**, so report generation, the sandboxed report viewer and the draft vault can be tried on a clean install. No message is sent and the SMS/phone gateway is not used.

- **Off by default.** It runs only when the environment variable `HMR_DEV_TOOLS` is exactly `1`. Without it the command exits with code 5 and changes nothing.
- **No API route and no UI.** The only entry point is the command line, so a normal launch of the app cannot reach it.
- **Synthetic data only.** Names, dates, medicines and identifiers are fake and labelled DEV SEED. Never set `HMR_DEV_TOOLS` on a pharmacist's machine.

Run it against the same data and workspace folders the app uses (see `app-config.json` for `base`). On the installed app, in PowerShell:

```
$env:HMR_DEV_TOOLS = '1'
& 'C:\Path\To\hmr-engine.exe' --data-dir "$env:USERPROFILE\HMR-Desk-data" --workspace '<base from app-config.json>' --dev-seed-visit
```

Run it as the same Windows user as the app (the database key is tied to that user). Close the app first, then start it again to see the patient. The command prints the new patient id and folder as JSON.
