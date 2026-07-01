//! Cloud API keys in the OS keychain (Windows Credential Manager / macOS
//! Keychain via the `keyring` crate). Keys never touch source, config files,
//! or logs (CLAUDE.md guardrail).

use keyring::Entry;

const SERVICE: &str = "linguacast";

fn entry(name: &str) -> Result<Entry, String> {
    Entry::new(SERVICE, name).map_err(|e| format!("keychain entry error: {e}"))
}

pub fn set_secret(name: &str, value: &str) -> Result<(), String> {
    if value.is_empty() {
        // Empty input means "clear the stored key".
        return delete_secret(name);
    }
    entry(name)?
        .set_password(value)
        .map_err(|e| format!("cannot store secret: {e}"))
}

pub fn get_secret(name: &str) -> Result<Option<String>, String> {
    match entry(name)?.get_password() {
        Ok(v) => Ok(Some(v)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(format!("cannot read secret: {e}")),
    }
}

pub fn delete_secret(name: &str) -> Result<(), String> {
    match entry(name)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(format!("cannot delete secret: {e}")),
    }
}
