//! Encodages d'image ROS -> pixels RVB (ou gris) contigus, réduits à la
//! largeur demandée par moyenne de zone : chaque pixel source compte une fois,
//! ce qui lisse le bruit du capteur au lieu de créer du crénelage.

/// Image prête pour l'encodeur JPEG.
pub struct Picture {
    pub width: usize,
    pub height: usize,
    /// 3 (RVB) ou 1 (gris).
    pub channels: usize,
    pub data: Vec<u8>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Format {
    Rgb,
    Bgr,
    Rgba,
    Bgra,
    Mono,
    Yuyv,
    Uyvy,
}

/// Format et octets par pixel source, pour les encodages courants de usb_cam / OpenCV.
fn format(encoding: &str) -> Option<(Format, usize)> {
    Some(match encoding {
        "rgb8" => (Format::Rgb, 3),
        "bgr8" | "8UC3" => (Format::Bgr, 3),
        "rgba8" => (Format::Rgba, 4),
        "bgra8" | "8UC4" => (Format::Bgra, 4),
        "mono8" | "8UC1" => (Format::Mono, 1),
        "yuv422_yuy2" | "yuyv" => (Format::Yuyv, 2),
        "yuv422" | "uyvy" => (Format::Uyvy, 2),
        _ => return None,
    })
}

/// Taille de sortie : jamais d'agrandissement, proportions conservées.
pub fn target_size(width: usize, height: usize, max_width: usize) -> (usize, usize) {
    let out_width = width.min(max_width).max(1);
    let out_height = ((height * out_width + width / 2) / width).clamp(1, height);
    (out_width, out_height)
}

/// YUV BT.601 (plage limitée des webcams) -> RVB.
fn yuv(y: u8, u: u8, v: u8, out: &mut [u8]) {
    let c = 298 * (i32::from(y) - 16);
    let d = i32::from(u) - 128;
    let e = i32::from(v) - 128;
    out[0] = ((c + 409 * e + 128) >> 8).clamp(0, 255) as u8;
    out[1] = ((c - 100 * d - 208 * e + 128) >> 8).clamp(0, 255) as u8;
    out[2] = ((c + 516 * d + 128) >> 8).clamp(0, 255) as u8;
}

/// Convertit une ligne source en RVB (ou gris) dans `line`.
fn convert_row(kind: Format, row: &[u8], line: &mut [u8]) {
    match kind {
        Format::Rgb | Format::Mono => line.copy_from_slice(&row[..line.len()]),
        Format::Bgr => {
            for (out, pixel) in line.chunks_exact_mut(3).zip(row.chunks_exact(3)) {
                out.copy_from_slice(&[pixel[2], pixel[1], pixel[0]]);
            }
        }
        Format::Rgba => {
            for (out, pixel) in line.chunks_exact_mut(3).zip(row.chunks_exact(4)) {
                out.copy_from_slice(&pixel[..3]);
            }
        }
        Format::Bgra => {
            for (out, pixel) in line.chunks_exact_mut(3).zip(row.chunks_exact(4)) {
                out.copy_from_slice(&[pixel[2], pixel[1], pixel[0]]);
            }
        }
        // Deux pixels partagent U et V : Y0 U Y1 V (YUYV) ou U Y0 V Y1 (UYVY).
        Format::Yuyv | Format::Uyvy => {
            for (out, pair) in line.chunks_exact_mut(6).zip(row.chunks_exact(4)) {
                let (y0, u, y1, v) = if kind == Format::Yuyv {
                    (pair[0], pair[1], pair[2], pair[3])
                } else {
                    (pair[1], pair[0], pair[3], pair[2])
                };
                yuv(y0, u, v, &mut out[..3]);
                yuv(y1, u, v, &mut out[3..]);
            }
        }
    }
}

/// Convertit un message `sensor_msgs/Image` et le réduit à `max_width`.
pub fn prepare(
    width: usize,
    height: usize,
    step: usize,
    encoding: &str,
    data: &[u8],
    max_width: usize,
) -> Result<Picture, String> {
    let (kind, bytes) = format(encoding).ok_or_else(|| {
        format!("Encodage {encoding} non pris en charge (rgb8, bgr8, rgba8, bgra8, mono8, yuv422)")
    })?;
    if width == 0 || height == 0 || width > 8192 || height > 8192 {
        return Err(format!("Taille d'image invalide : {width}×{height}"));
    }
    if matches!(kind, Format::Yuyv | Format::Uyvy) && width % 2 != 0 {
        return Err("Largeur impaire impossible en YUV 4:2:2".into());
    }
    let row_bytes = width * bytes;
    if step < row_bytes || data.len() < step * (height - 1) + row_bytes {
        return Err(format!(
            "Image tronquée : {} octets pour {width}×{height} (step {step})",
            data.len()
        ));
    }
    let channels = if kind == Format::Mono { 1 } else { 3 };
    let (out_width, out_height) = target_size(width, height, max_width);
    let mut line = vec![0u8; width * channels];
    let mut out = vec![0u8; out_width * out_height * channels];
    let row = |y: usize| &data[y * step..y * step + row_bytes];

    if (out_width, out_height) == (width, height) {
        for (y, target) in out.chunks_exact_mut(width * channels).enumerate() {
            convert_row(kind, row(y), target);
        }
    } else {
        // Chaque colonne / ligne source appartient à une seule case de sortie.
        let columns: Vec<usize> = (0..width).map(|x| x * out_width / width).collect();
        let mut per_column = vec![0u32; out_width];
        for &column in &columns {
            per_column[column] += 1;
        }
        let mut sums = vec![0u32; out_width * channels];
        let mut rows_in = 0u32;
        let mut current = 0usize;
        let mut flush = |sums: &mut [u32], rows_in: u32, y: usize| {
            let target = &mut out[y * out_width * channels..(y + 1) * out_width * channels];
            for (x, count) in per_column.iter().enumerate() {
                let n = count * rows_in;
                for c in 0..channels {
                    let i = x * channels + c;
                    target[i] = ((sums[i] + n / 2) / n) as u8;
                    sums[i] = 0;
                }
            }
        };
        for y in 0..height {
            let out_y = y * out_height / height;
            if out_y != current {
                flush(&mut sums, rows_in, current);
                rows_in = 0;
                current = out_y;
            }
            convert_row(kind, row(y), &mut line);
            for (x, &column) in columns.iter().enumerate() {
                let (source, target) = (x * channels, column * channels);
                for c in 0..channels {
                    sums[target + c] += u32::from(line[source + c]);
                }
            }
            rows_in += 1;
        }
        flush(&mut sums, rows_in, current);
    }
    Ok(Picture {
        width: out_width,
        height: out_height,
        channels,
        data: out,
    })
}

/// Rotation dans le sens horaire (0, 90, 180 ou 270°), pour une webcam
/// montée de côté (portrait : plus de champ vertical pour un corps debout).
pub fn rotate(picture: Picture, degrees: u16) -> Picture {
    let (w, h, c) = (picture.width, picture.height, picture.channels);
    if !matches!(degrees, 90 | 180 | 270) {
        return picture;
    }
    let (out_w, out_h) = if degrees == 180 { (w, h) } else { (h, w) };
    let mut data = vec![0u8; picture.data.len()];
    for y in 0..out_h {
        for x in 0..out_w {
            // Pixel source qui arrive en (x, y) après rotation.
            let (sx, sy) = match degrees {
                90 => (y, h - 1 - x),
                180 => (w - 1 - x, h - 1 - y),
                _ => (w - 1 - y, x),
            };
            let (to, from) = ((y * out_w + x) * c, (sy * w + sx) * c);
            data[to..to + c].copy_from_slice(&picture.data[from..from + c]);
        }
    }
    Picture {
        width: out_w,
        height: out_h,
        channels: c,
        data,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rotations_are_clockwise() {
        // 3×2 gris : 1 2 3 / 4 5 6
        let picture = || Picture { width: 3, height: 2, channels: 1, data: vec![1, 2, 3, 4, 5, 6] };
        let r = rotate(picture(), 90);
        assert_eq!((r.width, r.height, r.data), (2, 3, vec![4, 1, 5, 2, 6, 3]));
        let r = rotate(picture(), 180);
        assert_eq!((r.width, r.height, r.data), (3, 2, vec![6, 5, 4, 3, 2, 1]));
        let r = rotate(picture(), 270);
        assert_eq!((r.width, r.height, r.data), (2, 3, vec![3, 6, 2, 5, 1, 4]));
        assert_eq!(rotate(picture(), 0).data, vec![1, 2, 3, 4, 5, 6]);
        // Couleur : les 3 octets d'un pixel restent ensemble.
        let rgb = Picture { width: 2, height: 1, channels: 3, data: vec![1, 2, 3, 4, 5, 6] };
        assert_eq!(rotate(rgb, 90).data, vec![1, 2, 3, 4, 5, 6]);
    }

    #[test]
    fn target_keeps_aspect_ratio_and_never_upscales() {
        assert_eq!(target_size(640, 480, 480), (480, 360));
        assert_eq!(target_size(640, 480, 320), (320, 240));
        assert_eq!(target_size(320, 240, 640), (320, 240));
        assert_eq!(target_size(1, 1, 480), (1, 1));
    }

    #[test]
    fn bgr_and_padded_rows_become_rgb() {
        // 2×2 en bgr8 avec 2 octets de remplissage par ligne (step > width*3).
        let data = [0, 0, 255, 0, 255, 0, 9, 9, 255, 0, 0, 10, 20, 30, 9, 9];
        let picture = prepare(2, 2, 8, "bgr8", &data, 640).unwrap();
        assert_eq!(picture.channels, 3);
        assert_eq!(picture.data, vec![255, 0, 0, 0, 255, 0, 0, 0, 255, 30, 20, 10]);
    }

    #[test]
    fn downscale_averages_areas() {
        // 4×2 gris -> 2×1 : moyenne de chaque carré 2×2.
        let data = [0, 100, 200, 200, 100, 200, 0, 40];
        let picture = prepare(4, 2, 4, "mono8", &data, 2).unwrap();
        assert_eq!((picture.width, picture.height, picture.channels), (2, 1, 1));
        assert_eq!(picture.data, vec![100, 110]);
    }

    #[test]
    fn rgba_and_yuv_inputs() {
        let picture = prepare(1, 1, 4, "rgba8", &[1, 2, 3, 4], 640).unwrap();
        assert_eq!(picture.data, vec![1, 2, 3]);
        // Gris moyen en YUYV : Y=126, U=V=128 -> environ (128, 128, 128).
        let picture = prepare(2, 1, 4, "yuv422_yuy2", &[126, 128, 126, 128], 640).unwrap();
        assert!(picture.data.iter().all(|&v| (125..=131).contains(&v)), "{:?}", picture.data);
        // Rouge en UYVY : U bas, V haut.
        let picture = prepare(2, 1, 4, "uyvy", &[90, 81, 240, 81], 640).unwrap();
        assert!(picture.data[0] > 200 && picture.data[1] < 40 && picture.data[2] < 40, "{:?}", picture.data);
    }

    #[test]
    fn malformed_images_are_rejected() {
        assert!(prepare(2, 2, 6, "rgb8", &[0; 11], 640).is_err());
        assert!(prepare(2, 2, 5, "rgb8", &[0; 12], 640).is_err());
        assert!(prepare(3, 1, 6, "yuv422_yuy2", &[0; 6], 640).is_err());
        assert!(prepare(2, 2, 6, "32FC1", &[0; 12], 640).is_err());
        assert!(prepare(0, 2, 6, "rgb8", &[], 640).is_err());
    }
}
