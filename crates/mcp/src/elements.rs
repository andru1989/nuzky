//! The user's saved elements: clips kept beside the projects with the media they use, such as a text in its style,
//! a sticker, or a picture with its fade, to put into any project again. The media stays where it is; an element
//! names the files as the project it came from did.

use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, ensure};
use nuzky_engine::Project;
use nuzky_engine::edit::{CopiedClip, EditCmd, new_id};
use nuzky_engine::model::{Asset, Background, ClipContent};
use serde::{Deserialize, Serialize};

/// Most clips in one element.
pub const MAX_CLIPS: usize = 50;
/// Most characters in an element's name.
pub const MAX_NAME_CHARS: usize = 60;

/// One change of the list at a time: two saves at once, as from a double click, each read the list without the other's
/// element and the second write lost the first.
static CHANGING: Mutex<()> = Mutex::new(());

fn changing() -> MutexGuard<'static, ()> {
    CHANGING.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// One saved element: clips as copied, with the media they show.
#[cfg_attr(feature = "ts", derive(ts_rs::TS))]
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SavedElement {
    pub id: String,
    pub name: String,
    /// When it was saved, in milliseconds since the Unix epoch.
    pub saved_ms: u64,
    pub clips: Vec<CopiedClip>,
    pub assets: Vec<Asset>,
}

fn dir() -> Result<PathBuf> {
    nuzky_engine::data_dir().context("STORE_UNAVAILABLE: no data directory for saved elements")
}

fn path() -> Result<PathBuf> {
    Ok(dir()?.join("elements.json"))
}

/// Where the picture of element `id` is kept, a PNG the app draws when it saves the element.
pub fn preview_path(id: &str) -> Result<PathBuf> {
    ensure!(valid_id(id), "INVALID_ARGUMENTS: not an element id");
    Ok(dir()?.join("elements").join(format!("{id}.png")))
}

fn valid_id(id: &str) -> bool {
    (1..=40).contains(&id.len()) && id.bytes().all(|b| b.is_ascii_alphanumeric())
}

pub fn list() -> Result<Vec<SavedElement>> {
    let bytes = match std::fs::read(path()?) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(vec![]),
        Err(error) => return Err(error).context("STORE_UNREADABLE: cannot read your saved elements"),
    };
    serde_json::from_slice(&bytes).context("STORE_UNREADABLE: your saved elements file is damaged")
}

fn write(elements: &[SavedElement]) -> Result<()> {
    let path = path()?;
    std::fs::create_dir_all(path.parent().unwrap()).context("STORE_WRITE_FAILED: cannot save your elements")?;
    nuzky_session::write_json_atomic(&path, &elements).context("STORE_WRITE_FAILED: cannot save your elements")
}

fn clean_name(name: &str) -> Result<String> {
    let name = name.trim();
    ensure!(
        (1..=MAX_NAME_CHARS).contains(&name.chars().count()) && !name.contains(['\n', '\r']),
        "INVALID_ARGUMENTS: an element's name needs 1 to {MAX_NAME_CHARS} characters on one line"
    );
    Ok(name.into())
}

/// The media a clip shows: its own file and an image behind its person.
fn media_of(clip: &CopiedClip) -> Vec<&str> {
    match &clip.clip.content {
        ClipContent::Media { asset_id, background, .. } => {
            let mut ids = vec![asset_id.as_str()];
            if let Background::Image { asset_id } = background {
                ids.push(asset_id);
            }
            ids
        }
        ClipContent::Text { .. } => vec![],
    }
}

/// An empty project of `canvas` holding the element at the start, checked as every project is. Saving refuses an
/// element this fails for, so one that was saved always goes into a project, and the app draws its picture from it.
pub fn as_project(element: &SavedElement, canvas: (u32, u32)) -> Result<Project> {
    let mut project = Project::new(&element.name);
    project.apply(EditCmd::SetCanvas { width: canvas.0, height: canvas.1, background: None, background_blur: None })?;
    if !element.assets.is_empty() {
        project.apply(EditCmd::AddAssets { assets: element.assets.clone() })?;
    }
    project.apply(EditCmd::PasteClips { clips: element.clips.clone(), at_us: 0 })?;
    nuzky_session::validate(&project)?;
    Ok(project)
}

fn check(element: &SavedElement) -> Result<()> {
    ensure!(valid_id(&element.id), "INVALID_ARGUMENTS: not an element id");
    ensure!(
        (1..=MAX_CLIPS).contains(&element.clips.len()),
        "INVALID_ARGUMENTS: an element holds 1 to {MAX_CLIPS} clips"
    );
    for asset in &element.assets {
        nuzky_session::local_media_path(&asset.path)?;
    }
    let used: Vec<&str> = element.clips.iter().flat_map(media_of).collect();
    ensure!(
        used.iter().all(|id| element.assets.iter().any(|a| a.id == *id)),
        "INVALID_ARGUMENTS: a clip of the element shows media the element does not have"
    );
    ensure!(
        element.assets.iter().all(|a| used.contains(&a.id.as_str())),
        "INVALID_ARGUMENTS: the element has media none of its clips shows"
    );
    as_project(element, (1080, 1920)).map(|_| ()).map_err(|error| {
        anyhow::anyhow!("INVALID_ARGUMENTS: {}", error.to_string().trim_start_matches("INVALID_PROJECT: "))
    })
}

/// The clips `clip_ids` of `project` as an element named `name`, with the media they show.
pub fn from_project(project: &Project, clip_ids: &[String], name: &str) -> Result<SavedElement> {
    let mut clips: Vec<CopiedClip> = project
        .tracks
        .iter()
        .flat_map(|t| {
            t.clips.iter().filter(|c| clip_ids.contains(&c.id)).map(|clip| CopiedClip {
                clip: clip.clone(),
                track_id: t.id.clone(),
                track_kind: t.kind,
                keep_in_place: t.keep_in_place,
            })
        })
        .collect();
    ensure!(!clips.is_empty(), "INVALID_ARGUMENTS: select the clips to save first");
    clips.sort_by_key(|c| c.clip.start_us);
    let used: Vec<&str> = clips.iter().flat_map(media_of).collect();
    let assets = project.assets.iter().filter(|a| used.contains(&a.id.as_str())).cloned().collect();
    let saved_ms = SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_millis() as u64);
    Ok(SavedElement { id: new_id(), name: clean_name(name)?, saved_ms, clips, assets })
}

/// Saves `element` first in the list, or back in place when its id is there, as Undo of a delete puts it back.
pub fn save(mut element: SavedElement) -> Result<Vec<SavedElement>> {
    let _changing = changing();
    element.name = clean_name(&element.name)?;
    check(&element)?;
    let mut elements = list()?;
    match elements.iter().position(|e| e.id == element.id) {
        Some(i) => elements[i] = element,
        None => elements.insert(0, element),
    }
    write(&elements)?;
    Ok(elements)
}

/// Puts a deleted element back at `index`.
pub fn restore(element: SavedElement, index: usize) -> Result<Vec<SavedElement>> {
    let _changing = changing();
    check(&element)?;
    let mut elements = list()?;
    elements.retain(|e| e.id != element.id);
    elements.insert(index.min(elements.len()), element);
    write(&elements)?;
    Ok(elements)
}

pub fn rename(id: &str, name: &str) -> Result<Vec<SavedElement>> {
    let _changing = changing();
    let mut elements = list()?;
    let element = elements.iter_mut().find(|e| e.id == id).context("UNKNOWN_ELEMENT: no saved element with that id")?;
    element.name = clean_name(name)?;
    write(&elements)?;
    Ok(elements)
}

/// Deletes element `id`, returning it and where it was, so Undo can put it back. Its picture stays until another
/// element is saved, for that Undo.
pub fn delete(id: &str) -> Result<(SavedElement, usize)> {
    let _changing = changing();
    let mut elements = list()?;
    let index = elements.iter().position(|e| e.id == id).context("UNKNOWN_ELEMENT: no saved element with that id")?;
    let element = elements.remove(index);
    write(&elements)?;
    Ok((element, index))
}

/// Removes the pictures of elements that are gone.
pub fn sweep_previews() -> Result<()> {
    let _changing = changing();
    let keep: Vec<String> = list()?.into_iter().map(|e| format!("{}.png", e.id)).collect();
    let Ok(entries) = std::fs::read_dir(dir()?.join("elements")) else { return Ok(()) };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.ends_with(".png") && !keep.contains(&name) {
            std::fs::remove_file(entry.path()).ok();
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use nuzky_engine::model::AssetKind;

    fn sticker(dir: &std::path::Path) -> Asset {
        let path = dir.join("arrow.png");
        std::fs::write(&path, b"png").unwrap();
        Asset {
            id: "arrow1".into(),
            name: "arrow.png".into(),
            path: path.to_string_lossy().into(),
            kind: AssetKind::Image,
            duration_us: 0,
            width: 200,
            height: 100,
            fps: 0.0,
            has_audio: false,
            rotation: 0,
            mirror: false,
            credit: None,
            part: None,
        }
    }

    /// An element keeps exactly the media its clips show, so another project gets the files it needs and no more.
    #[test]
    fn an_element_takes_the_media_its_clips_show() {
        let dir = std::env::temp_dir().join(format!("nuzky-elements-{}", new_id()));
        std::fs::create_dir_all(&dir).unwrap();
        let mut project = Project::new("Source");
        let arrow = sticker(&dir);
        let mut other = arrow.clone();
        other.id = "other1".into();
        project.apply(EditCmd::AddAssets { assets: vec![arrow.clone(), other] }).unwrap();
        project
            .apply(EditCmd::AddClip { asset_id: "arrow1".into(), start_us: Some(2_000_000), track_id: None })
            .unwrap();
        let ids: Vec<String> = project.tracks.iter().flat_map(|t| t.clips.iter().map(|c| c.id.clone())).collect();
        let element = from_project(&project, &ids, "  Arrow  ").unwrap();
        assert_eq!(element.name, "Arrow");
        assert_eq!(element.assets, vec![arrow]);
        check(&element).unwrap();
        let mut missing = element.clone();
        missing.assets.clear();
        assert!(check(&missing).is_err(), "a clip without its media is refused");
        assert!(from_project(&project, &[], "x").is_err());
        assert!(clean_name(&"x".repeat(MAX_NAME_CHARS + 1)).is_err());
        std::fs::remove_dir_all(dir).unwrap();
    }

    /// Saves that arrive together, as from a double click, keep every element: each reads the list the one before
    /// wrote. Runs in a child process with a data folder of its own.
    #[test]
    fn saves_at_once_keep_every_element() {
        if std::env::var_os("NUZKY_ELEMENTS_TEST").is_none() {
            let dir = std::env::temp_dir().join(format!("nuzky-elements-{}", new_id()));
            std::fs::create_dir_all(&dir).unwrap();
            let spawning = crate::model_download::CHILD_SPAWN.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
            let mut child = std::process::Command::new(std::env::current_exe().unwrap())
                .args(["--exact", "elements::tests::saves_at_once_keep_every_element", "--nocapture"])
                .env("NUZKY_ELEMENTS_TEST", "1")
                .env("NUZKY_DATA_DIR", &dir)
                .spawn()
                .unwrap();
            drop(spawning);
            let status = child.wait().unwrap();
            std::fs::remove_dir_all(dir).unwrap();
            assert!(status.success());
            return;
        }
        let mut project = Project::new("Source");
        let style = nuzky_engine::edit::caption_preset("reel").unwrap().style.clone();
        project.apply(EditCmd::AddText { start_us: 0, text: "Hook".into(), style }).unwrap();
        let ids: Vec<String> = project.tracks.iter().flat_map(|t| t.clips.iter().map(|c| c.id.clone())).collect();
        let threads: Vec<_> = (0..8)
            .map(|n| {
                let element = from_project(&project, &ids, &format!("Hook {n}")).unwrap();
                std::thread::spawn(move || save(element).unwrap())
            })
            .collect();
        for thread in threads {
            thread.join().unwrap();
        }
        assert_eq!(list().unwrap().len(), 8);
    }
}
