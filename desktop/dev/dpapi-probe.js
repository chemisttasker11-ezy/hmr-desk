'use strict';
// Real Windows Electron safeStorage cross-process crash recovery probe.
// Synthetic static string only. No patient data or credentials.
const {app,safeStorage}=require('electron');
const fs=require('node:fs');
const path=require('node:path');

const base=process.env.HMR_DPAPI_SMOKE_DIR;
const mode=process.env.HMR_DPAPI_SMOKE_MODE;
const marker='SYNTHETIC_DRAFT_TEST_NO_PHI_2026';
if (!base || !path.isAbsolute(base) || !['write','read'].includes(mode))
  throw Error('Explicit isolated DPAPI smoke directory and mode required');
fs.mkdirSync(path.join(base,'profile'),{recursive:true});
app.setPath('userData',path.join(base,'profile'));
app.whenReady().then(async()=>{
  const output=path.join(base,'draft-vault.bin');
  if (!safeStorage.isEncryptionAvailable()) throw Error('Windows safeStorage encryption unavailable');
  if (mode==='write'){
    const ciphertext=safeStorage.encryptString(marker);
    if (!Buffer.isBuffer(ciphertext)||ciphertext.includes(Buffer.from(marker)))
      throw Error('Encrypted draft unexpectedly contains plaintext marker');
    fs.writeFileSync(output,ciphertext,{flag:'wx',mode:0o600});
    // Chromium keeps the safeStorage key in "Local State" and flushes it
    // lazily. A hard kill before that flush makes the ciphertext unreadable,
    // so wait for the key file before reporting the draft as recoverable.
    const localState=path.join(base,'profile','Local State');
    const deadline=Date.now()+25000;
    while(!fs.existsSync(localState)&&Date.now()<deadline)
      await new Promise(resolve=>setTimeout(resolve,250));
    if(!fs.existsSync(localState)) throw Error('safeStorage key (Local State) was not persisted');
    fs.writeFileSync(path.join(base,'writer-ready'),'WRITTEN_SYNTHETIC_DRAFT');
    // Parent will force-terminate us to simulate a crash and leave ciphertext.
    setInterval(()=>{},1000);
  }else{
    const ciphertext=fs.readFileSync(output);
    if (ciphertext.includes(Buffer.from(marker))) throw Error('Plaintext draft on disk');
    const recovered=safeStorage.decryptString(ciphertext);
    if (recovered!==marker) throw Error('Protected draft did not survive process kill');
    // Electron is a GUI-subsystem binary on Windows, so stdout capture is
    // unreliable. Write the result to a file the smoke script reads.
    fs.writeFileSync(path.join(base,'reader-result.txt'),'SYNTHETIC_DPAPI_RECOVERY_PASS');
    process.stdout.write('SYNTHETIC_DPAPI_RECOVERY_PASS\n');
    app.exit(0);
  }
}).catch(error=>{
  try{fs.writeFileSync(path.join(base,'reader-error.txt'),String(error&&error.stack||error));}catch{}
  process.stderr.write(error.message+'\n');app.exit(1);
});
