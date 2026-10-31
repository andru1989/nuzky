//! The Saved tab: clips the user keeps beside the projects (`nuzky_mcp::elements`) to put into any project again,
//! each with a picture of it as the renderer draws it.

use base64::Engine as _;
use nuzky_engine::{Renderer, Wait};
use nuzky_mcp::elements::{self, SavedElement};
use serde::Serialize;
use tauri::{AppHandle, Manager};

use crate::{AppState, CmdResult, err};

/// Size of an element's picture in pixels, the 4:3 of the Saved tab's tiles.
const PREVIEW: (u32, u32) = (320, 240);

#[cfg_attr(test, derive(ts_rs::TS))]
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ElementView {
    #[serde(flatten)]
    #[cfg_attr(test, ts(flatten))]
    element: SavedElement,
    /// PNG data URL of the element as the renderer draws it in the project it was saved from; null without one.
    preview: Option<String>,
}

/// What Delete took out, for Undo to put back where it was.
#[cfg_attr(test, derive(ts_rs::TS))]
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DeletedElement {
    element: SavedElement,
    index: usize,
    elements: Vec<ElementView>,
}

fn preview(id: &str) -> Option<String> {
    let bytes = std::fs::read(elements::preview_path(id).ok()?).ok()?;
    Some(format!("data:image/png;base64,{}", base64::engine::general_purpose::STANDARD.encode(bytes)))
}

fn views(list: Vec<SavedElement>) -> Vec<ElementView> {
    list.into_iter().map(|element| ElementView { preview: preview(&element.id), element }).collect()
}

/// The part of the canvas around the layers of `project` at `at_us`, with a margin, in the tiles' 4:3 where the canvas
/// allows: a small text or sticker fills its tile instead of sitting in an empty frame.
fn framing(project: &nuzky_engine::Project, at_us: i64) -> (f32, f32, f32, f32) {
    let (cw, ch) = (project.canvas.width as f32, project.canvas.height as f32);
    let mut text = nuzky_engine::text::TextRenderer::new();
    let points: Vec<[f32; 2]> = nuzky_engine::render::layer_bounds(project, at_us, &mut text)
        .into_iter()
        .flat_map(|(_, corners, _)| corners)
        .collect();
    if points.is_empty() {
        return (0.0, 0.0, cw, ch);
    }
    let x0 = points.iter().map(|p| p[0]).fold(f32::MAX, f32::min).max(0.0);
    let y0 = points.iter().map(|p| p[1]).fold(f32::MAX, f32::min).max(0.0);
    let x1 = points.iter().map(|p| p[0]).fold(f32::MIN, f32::max).min(cw);
    let y1 = points.iter().map(|p| p[1]).fold(f32::MIN, f32::max).min(ch);
    if x1 - x0 < 1.0 || y1 - y0 < 1.0 {
        return (0.0, 0.0, cw, ch);
    }
    let margin = 0.08 * (x1 - x0).max(y1 - y0);
    let (mut w, mut h) = (x1 - x0 + 2.0 * margin, y1 - y0 + 2.0 * margin);
    let aspect = PREVIEW.0 as f32 / PREVIEW.1 as f32;
    if w / h < aspect {
        w = h * aspect;
    } else {
        h = w / aspect;
    }
    let (w, h) = (w.min(cw), h.min(ch));
    let x = ((x0 + x1) / 2.0 - w / 2.0).clamp(0.0, cw - w);
    let y = ((y0 + y1) / 2.0 - h / 2.0).clamp(0.0, ch - h);
    (x, y, w, h)
}

/// The element on a canvas of `canvas`, where all of its clips show, past their entry animations when it can, framed
/// around its layers.
fn draw(element: &SavedElement, canvas: (u32, u32)) -> anyhow::Result<Vec<u8>> {
    let project = elements::as_project(element, canvas)?;
    let clips: Vec<_> = project.tracks.iter().flat_map(|t| &t.clips).collect();
    let start = clips.iter().map(|c| c.start_us).max().unwrap_or(0);
    let end = clips.iter().map(|c| c.start_us + c.duration_us).min().unwrap_or(0);
    let at = if start < end { (start + end) / 2 } else { clips.first().map_or(0, |c| c.start_us + c.duration_us / 2) };
    let (x, y, w, h) = framing(&project, at);
    // The whole frame at the scale that gives the framed part the picture's size, at most 4096 px a side.
    let scale = (PREVIEW.0 as f32 / w).min(PREVIEW.1 as f32 / h).min(4096.0 / canvas.0.max(canvas.1) as f32);
    let even = |v: f32| ((v.round() as u32).max(2) + 1) & !1;
    let (fw, fh) = (even(canvas.0 as f32 * scale), even(canvas.1 as f32 * scale));
    let mut renderer = Renderer::new()?;
    let frame = renderer.render(&project, at, fw, fh, Wait::Exact, false)?;
    let (px, py) = (((x * scale) as u32).min(fw - 1), ((y * scale) as u32).min(fh - 1));
    let (pw, ph) = (((w * scale).round() as u32).clamp(1, fw - px), ((h * scale).round() as u32).clamp(1, fh - py));
    let mut rgba = Vec::with_capacity((pw * ph * 4) as usize);
    for row in py..py + ph {
        let from = ((row * fw + px) * 4) as usize;
        rgba.extend_from_slice(&frame[from..from + (pw * 4) as usize]);
    }
    let mut png = Vec::new();
    {
        let mut encoder = png::Encoder::new(&mut png, pw, ph);
        encoder.set_color(png::ColorType::Rgba);
        encoder.write_header()?.write_image_data(&rgba)?;
    }
    Ok(png)
}

#[tauri::command]
pub async fn saved_elements() -> CmdResult<Vec<ElementView>> {
    tauri::async_runtime::spawn_blocking(|| elements::list().map(views).map_err(err)).await.map_err(err)?
}

/// Saves the clips `clip_ids` of the open project as an element named `name`, first in the list.
#[tauri::command]
pub async fn save_element(app: AppHandle, name: String, clip_ids: Vec<String>) -> CmdResult<Vec<ElementView>> {
    let project = app.state::<AppState>().project()?;
    tauri::async_runtime::spawn_blocking(move || {
        let element = elements::from_project(&project, &clip_ids, &name).map_err(err)?;
        let list = elements::save(element.clone()).map_err(err)?;
        // The element is kept without its picture when drawing it fails, as on a computer without a usable GPU.
        match draw(&element, (project.canvas.width, project.canvas.height)) {
            Ok(png) => {
                let written = elements::preview_path(&element.id).and_then(|path| {
                    std::fs::create_dir_all(path.parent().unwrap())?;
                    Ok(std::fs::write(path, png)?)
                });
                if let Err(error) = written {
                    log::warn!("Cannot keep the picture of a saved element: {error:#}");
                }
            }
            Err(error) => log::warn!("Cannot draw a saved element: {error:#}"),
        }
        elements::sweep_previews().ok();
        Ok(views(list))
    })
    .await
    .map_err(err)?
}

#[tauri::command]
pub async fn rename_element(id: String, name: String) -> CmdResult<Vec<ElementView>> {
    tauri::async_runtime::spawn_blocking(move || elements::rename(&id, &name).map(views).map_err(err))
        .await
        .map_err(err)?
}

#[tauri::command]
pub async fn delete_element(id: String) -> CmdResult<DeletedElement> {
    tauri::async_runtime::spawn_blocking(move || {
        let (element, index) = elements::delete(&id).map_err(err)?;
        let elements = views(elements::list().map_err(err)?);
        Ok(DeletedElement { element, index, elements })
    })
    .await
    .map_err(err)?
}

/// Undo of Delete: the element back where it was, with its picture, which Delete left in place.
#[tauri::command]
pub async fn restore_element(element: SavedElement, index: usize) -> CmdResult<Vec<ElementView>> {
    tauri::async_runtime::spawn_blocking(move || elements::restore(element, index).map(views).map_err(err))
        .await
        .map_err(err)?
}
