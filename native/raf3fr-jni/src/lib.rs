use std::collections::HashMap;
use std::collections::hash_map::Entry;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, LazyLock, Mutex};

use jni::EnvUnowned;
use jni::errors::ThrowRuntimeExAndDefault;
use jni::objects::{JClass, JString};
use jni::sys::jboolean;
use serde_json::json;

static ACTIVE_JOBS: LazyLock<Mutex<HashMap<String, Arc<AtomicBool>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

struct ActiveJob(String);

impl Drop for ActiveJob {
    fn drop(&mut self) {
        if let Ok(mut jobs) = ACTIVE_JOBS.lock() {
            jobs.remove(&self.0);
        }
    }
}

fn register_job(job_id: String) -> Result<(ActiveJob, Arc<AtomicBool>), String> {
    if job_id.is_empty() {
        return Err("job ID is empty".to_owned());
    }
    let cancellation = Arc::new(AtomicBool::new(false));
    let mut jobs = ACTIVE_JOBS
        .lock()
        .map_err(|_| "native job registry is unavailable".to_owned())?;
    match jobs.entry(job_id.clone()) {
        Entry::Occupied(_) => return Err(format!("job {job_id} is already active")),
        Entry::Vacant(entry) => {
            entry.insert(cancellation.clone());
        }
    }
    Ok((ActiveJob(job_id), cancellation))
}

fn cancel_job(job_id: &str) -> bool {
    let found = ACTIVE_JOBS
        .lock()
        .ok()
        .and_then(|jobs| jobs.get(job_id).cloned());
    if let Some(cancellation) = found {
        cancellation.store(true, Ordering::Relaxed);
        true
    } else {
        false
    }
}

fn response(result: raf3fr_core::Result<serde_json::Value>) -> String {
    let value = match result {
        Ok(value) => json!({"ok":true, "result":value}),
        Err(error) => json!({"ok":false, "error":error.to_string()}),
    };
    serde_json::to_string(&value).unwrap_or_else(|error| {
        format!(r#"{{"ok":false,"error":"failed to encode native response: {error}"}}"#)
    })
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_raf3fr_app_engine_NativeEngine_convert<'local>(
    mut unowned_env: EnvUnowned<'local>,
    _class: JClass<'local>,
    source: JString<'local>,
    donor: JString<'local>,
    output: JString<'local>,
    options_json: JString<'local>,
    job_id: JString<'local>,
) -> JString<'local> {
    unowned_env
        .with_env(|env| {
            let source = source.try_to_string(env)?;
            let donor = donor.try_to_string(env)?;
            let output = output.try_to_string(env)?;
            let options_json = options_json.try_to_string(env)?;
            let job_id = job_id.try_to_string(env)?;
            let rendered =
                match serde_json::from_str::<raf3fr_core::ConversionOptions>(&options_json) {
                    Ok(options) => match register_job(job_id) {
                        Ok((_job, cancellation)) => response(raf3fr_core::convert_cancellable(
                            source,
                            donor,
                            output,
                            options,
                            Some(&cancellation),
                        )),
                        Err(error) => json!({"ok":false, "error":error}).to_string(),
                    },
                    Err(error) => {
                        json!({"ok":false, "error":format!("invalid conversion options: {error}")})
                            .to_string()
                    }
                };
            JString::from_str(env, rendered)
        })
        .resolve::<ThrowRuntimeExAndDefault>()
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_raf3fr_app_engine_NativeEngine_cancel<'local>(
    mut unowned_env: EnvUnowned<'local>,
    _class: JClass<'local>,
    job_id: JString<'local>,
) -> jboolean {
    unowned_env
        .with_env(|env| {
            let job_id = job_id.try_to_string(env)?;
            let cancelled = cancel_job(&job_id);
            Ok::<jboolean, jni::errors::Error>(cancelled)
        })
        .resolve::<ThrowRuntimeExAndDefault>()
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_com_raf3fr_app_engine_NativeEngine_verify<'local>(
    mut unowned_env: EnvUnowned<'local>,
    _class: JClass<'local>,
    donor: JString<'local>,
    candidate: JString<'local>,
    source: JString<'local>,
) -> JString<'local> {
    unowned_env
        .with_env(|env| {
            let donor = donor.try_to_string(env)?;
            let candidate = candidate.try_to_string(env)?;
            let source = source.try_to_string(env)?;
            let source = (!source.is_empty()).then(|| Path::new(&source));
            let rendered = response(raf3fr_core::verify(donor, candidate, source).and_then(
                |report| {
                    serde_json::to_value(report).map_err(|error| {
                        raf3fr_core::Error::InvalidMetadata(format!(
                            "failed to encode verification report: {error}"
                        ))
                    })
                },
            ));
            JString::from_str(env, rendered)
        })
        .resolve::<ThrowRuntimeExAndDefault>()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn native_failures_are_returned_as_structured_json() {
        let rendered = response(Err(raf3fr_core::Error::InvalidMetadata(
            "test failure".to_owned(),
        )));
        let parsed: serde_json::Value = serde_json::from_str(&rendered).unwrap();
        assert_eq!(parsed["ok"], false);
        assert!(parsed["error"].as_str().unwrap().contains("test failure"));
    }

    #[test]
    fn partial_option_json_uses_product_defaults() {
        let options: raf3fr_core::ConversionOptions =
            serde_json::from_str(r#"{"vignetting_strength":1.0}"#).unwrap();
        assert_eq!(options.white_balance, raf3fr_core::WhiteBalanceMode::Auto);
        assert_eq!(
            options.sensor_mapping,
            raf3fr_core::SensorMappingMode::WbAdaptiveBootstrap
        );
        assert_eq!(options.distortion_strength, 1.0);
        assert_eq!(
            options.distortion_model,
            raf3fr_core::DistortionModel::CameraJpeg
        );
        assert_eq!(options.iso_policy, raf3fr_core::IsoPolicy::HnnrStable);
        assert_eq!(options.chromatic_aberration_strength, 1.0);
        assert_eq!(options.vignetting_strength, 1.0);
    }

    #[test]
    fn duplicate_job_ids_are_rejected_and_drop_releases_them() {
        let (guard, cancellation) = register_job("job-1".to_owned()).unwrap();
        assert!(!cancellation.load(Ordering::Relaxed));
        assert!(register_job("job-1".to_owned()).is_err());
        assert!(cancel_job("job-1"));
        assert!(cancellation.load(Ordering::Relaxed));
        drop(guard);
        assert!(!cancel_job("job-1"));
        assert!(register_job("job-1".to_owned()).is_ok());
    }
}
