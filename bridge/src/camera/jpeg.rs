//! Encodeur JPEG baseline écrit pour le bridge, sans dépendance externe.
//!
//! Chaîne de compression :
//! 1. RVB -> YCbCr, puis sous-échantillonnage 4:2:0 de la couleur
//!    (l'œil voit moins la couleur que la luminosité : 2 fois moins de données) ;
//! 2. DCT 8×8 : l'énergie d'un bloc se concentre dans quelques coefficients ;
//! 3. quantification (tables de l'annexe K, échelle de qualité IJG) :
//!    les hautes fréquences, peu visibles, deviennent nulles ;
//! 4. zigzag puis codage des suites de zéros et Huffman (tables standard).
//!
//! Une image en niveaux de gris n'a qu'une composante (Y).

/// Position zigzag i -> indice naturel (ligne * 8 + colonne) du coefficient.
const ZIGZAG: [usize; 64] = [
    0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27,
    20, 13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58,
    59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
];

/// Tables de quantification de référence (annexe K.1), ordre naturel.
const LUMA_QUANT: [u8; 64] = [
    16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69,
    56, 14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104,
    113, 92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
];
const CHROMA_QUANT: [u8; 64] = [
    17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99,
    99, 47, 66, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
];

/// Tables de Huffman standard (annexe K.3) : nombre de codes par longueur, symboles.
const DC_LUMA_BITS: [u8; 16] = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0];
const DC_CHROMA_BITS: [u8; 16] = [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0];
const DC_VALUES: [u8; 12] = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const AC_LUMA_BITS: [u8; 16] = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d];
const AC_LUMA_VALUES: [u8; 162] = [
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61,
    0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52,
    0xd1, 0xf0, 0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x25,
    0x26, 0x27, 0x28, 0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45,
    0x46, 0x47, 0x48, 0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64,
    0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83,
    0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99,
    0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6,
    0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3,
    0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8,
    0xe9, 0xea, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa,
];
const AC_CHROMA_BITS: [u8; 16] = [0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77];
const AC_CHROMA_VALUES: [u8; 162] = [
    0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61,
    0x71, 0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91, 0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33,
    0x52, 0xf0, 0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34, 0xe1, 0x25, 0xf1, 0x17, 0x18,
    0x19, 0x1a, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44,
    0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63,
    0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a,
    0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97,
    0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4,
    0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca,
    0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7,
    0xe8, 0xe9, 0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa,
];

/// Qualité acceptée. Au-delà de 95, les coefficients dépassent les
/// catégories du JPEG baseline et le gain visuel est nul.
pub const MIN_QUALITY: u8 = 10;
pub const MAX_QUALITY: u8 = 95;

/// Code de Huffman de chaque symbole (0 à 255).
struct Huffman {
    code: [u16; 256],
    size: [u8; 256],
}

impl Huffman {
    /// Codes canoniques (annexe C) : même longueur = codes consécutifs.
    fn new(bits: &[u8; 16], values: &[u8]) -> Self {
        let mut table = Self {
            code: [0; 256],
            size: [0; 256],
        };
        let mut code: u32 = 0;
        let mut k = 0;
        for (length, &count) in bits.iter().enumerate() {
            for _ in 0..count {
                let symbol = values[k] as usize;
                table.code[symbol] = code as u16;
                table.size[symbol] = length as u8 + 1;
                code += 1;
                k += 1;
            }
            code <<= 1;
        }
        table
    }
}

/// Écriture bit à bit ; un octet 0xFF est suivi de 0x00 (« byte stuffing »).
struct BitWriter {
    out: Vec<u8>,
    acc: u32,
    count: u32,
}

impl BitWriter {
    fn put(&mut self, bits: u32, size: u32) {
        if size == 0 {
            return;
        }
        // acc garde moins de 8 bits : 8 + 16 bits tiennent dans un u32.
        self.acc = (self.acc << size) | (bits & ((1 << size) - 1));
        self.count += size;
        while self.count >= 8 {
            self.count -= 8;
            let byte = (self.acc >> self.count) as u8;
            self.out.push(byte);
            if byte == 0xFF {
                self.out.push(0);
            }
        }
        self.acc &= (1 << self.count) - 1;
    }

    fn symbol(&mut self, table: &Huffman, symbol: u8) {
        let s = symbol as usize;
        self.put(table.code[s].into(), table.size[s].into());
    }

    /// Complète le dernier octet avec des 1, comme l'exige la norme.
    fn flush(&mut self) {
        if self.count > 0 {
            let pad = 8 - self.count;
            self.put((1 << pad) - 1, pad);
        }
    }
}

/// Nombre de bits de |v| (catégorie JPEG).
fn category(value: i32) -> u32 {
    32 - value.unsigned_abs().leading_zeros()
}

/// Bits transmis après la catégorie : complément à un pour un négatif.
fn magnitude_bits(value: i32) -> u32 {
    if value < 0 {
        (value - 1) as u32
    } else {
        value as u32
    }
}

/// Table de quantification adaptée à la qualité (formule IJG / libjpeg).
fn scaled_table(base: &[u8; 64], quality: u8) -> [u8; 64] {
    let quality = u32::from(quality.clamp(1, 100));
    let scale = if quality < 50 {
        5000 / quality
    } else {
        200 - 2 * quality
    };
    base.map(|value| ((u32::from(value) * scale + 50) / 100).clamp(1, 255) as u8)
}

/// Matrice de la DCT : m[u][x] = c(u)/2 · cos((2x+1)uπ/16).
fn dct_matrix() -> [[f32; 8]; 8] {
    let mut m = [[0f32; 8]; 8];
    for (u, row) in m.iter_mut().enumerate() {
        let c = if u == 0 { std::f32::consts::FRAC_1_SQRT_2 } else { 1.0 };
        for (x, value) in row.iter_mut().enumerate() {
            let angle = ((2 * x + 1) * u) as f32 * std::f32::consts::PI / 16.0;
            *value = c / 2.0 * angle.cos();
        }
    }
    m
}

/// État de codage d'une composante : table, prédicteur DC.
struct Component<'a> {
    reciprocal: [f32; 64],
    dc: &'a Huffman,
    ac: &'a Huffman,
    previous_dc: i32,
}

impl<'a> Component<'a> {
    fn new(table: &[u8; 64], dc: &'a Huffman, ac: &'a Huffman) -> Self {
        Self {
            reciprocal: table.map(|q| 1.0 / f32::from(q)),
            dc,
            ac,
            previous_dc: 0,
        }
    }
}

struct Encoder<'a> {
    dct: [[f32; 8]; 8],
    writer: BitWriter,
    luma: Component<'a>,
    chroma_blue: Component<'a>,
    chroma_red: Component<'a>,
}

impl Encoder<'_> {
    /// DCT séparable (lignes puis colonnes), quantification puis codage entropique.
    fn block(&mut self, samples: &[f32; 64], which: usize) {
        let m = &self.dct;
        let mut rows = [0f32; 64];
        for y in 0..8 {
            for u in 0..8 {
                let mut sum = 0.0;
                for x in 0..8 {
                    sum += samples[y * 8 + x] * m[u][x];
                }
                rows[y * 8 + u] = sum;
            }
        }
        let component = match which {
            0 => &mut self.luma,
            1 => &mut self.chroma_blue,
            _ => &mut self.chroma_red,
        };
        let mut zigzag = [0i32; 64];
        for (position, &natural) in ZIGZAG.iter().enumerate() {
            let (v, u) = (natural / 8, natural % 8);
            let mut sum = 0.0;
            for y in 0..8 {
                sum += m[v][y] * rows[y * 8 + u];
            }
            // Bornes du baseline 8 bits : catégorie ≤ 10 pour AC, ≤ 11 pour l'écart DC.
            zigzag[position] = ((sum * component.reciprocal[natural]).round() as i32).clamp(-1023, 1023);
        }

        let writer = &mut self.writer;
        let difference = zigzag[0] - component.previous_dc;
        component.previous_dc = zigzag[0];
        let size = category(difference);
        writer.symbol(component.dc, size as u8);
        writer.put(magnitude_bits(difference), size);

        let mut run = 0;
        for &value in &zigzag[1..] {
            if value == 0 {
                run += 1;
                continue;
            }
            while run > 15 {
                writer.symbol(component.ac, 0xF0); // 16 zéros (ZRL)
                run -= 16;
            }
            let size = category(value);
            writer.symbol(component.ac, ((run << 4) | size) as u8);
            writer.put(magnitude_bits(value), size);
            run = 0;
        }
        if run > 0 {
            writer.symbol(component.ac, 0x00); // fin de bloc (EOB)
        }
    }
}

fn segment(out: &mut Vec<u8>, marker: u8, payload: &[u8]) {
    out.extend_from_slice(&[0xFF, marker]);
    out.extend_from_slice(&((payload.len() + 2) as u16).to_be_bytes());
    out.extend_from_slice(payload);
}

fn headers(out: &mut Vec<u8>, width: usize, height: usize, color: bool, luma: &[u8; 64], chroma: &[u8; 64]) {
    out.extend_from_slice(&[0xFF, 0xD8]); // SOI
    segment(out, 0xE0, b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0"); // APP0
    let mut tables = Vec::new();
    for (id, table) in [(0u8, luma), (1u8, chroma)].iter().take(if color { 2 } else { 1 }) {
        tables.push(*id);
        tables.extend(ZIGZAG.iter().map(|&natural| table[natural]));
    }
    segment(out, 0xDB, &tables); // DQT
    let mut frame = vec![8];
    frame.extend_from_slice(&(height as u16).to_be_bytes());
    frame.extend_from_slice(&(width as u16).to_be_bytes());
    if color {
        // Y échantillonné 2×2, Cb et Cr 1×1 : 4:2:0.
        frame.extend_from_slice(&[3, 1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1]);
    } else {
        frame.extend_from_slice(&[1, 1, 0x11, 0]);
    }
    segment(out, 0xC0, &frame); // SOF0 : baseline
    let mut huffman = Vec::new();
    let mut add = |class_id: u8, bits: &[u8; 16], values: &[u8]| {
        huffman.push(class_id);
        huffman.extend_from_slice(bits);
        huffman.extend_from_slice(values);
    };
    add(0x00, &DC_LUMA_BITS, &DC_VALUES);
    add(0x10, &AC_LUMA_BITS, &AC_LUMA_VALUES);
    if color {
        add(0x01, &DC_CHROMA_BITS, &DC_VALUES);
        add(0x11, &AC_CHROMA_BITS, &AC_CHROMA_VALUES);
    }
    segment(out, 0xC4, &huffman); // DHT
    let scan: &[u8] = if color {
        &[3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0]
    } else {
        &[1, 1, 0x00, 0, 63, 0]
    };
    segment(out, 0xDA, scan); // SOS
}

/// Encode des pixels contigus (RVB si `channels` = 3, gris si 1).
pub fn encode(pixels: &[u8], width: usize, height: usize, channels: usize, quality: u8) -> Result<Vec<u8>, String> {
    if width == 0 || height == 0 || width > 65535 || height > 65535 {
        return Err(format!("Taille d'image invalide : {width}×{height}"));
    }
    if channels != 1 && channels != 3 {
        return Err(format!("{channels} canaux : 1 (gris) ou 3 (RVB) attendus"));
    }
    if pixels.len() < width * height * channels {
        return Err("Données d'image incomplètes".into());
    }
    let color = channels == 3;
    let quality = quality.clamp(MIN_QUALITY, MAX_QUALITY);
    let luma_table = scaled_table(&LUMA_QUANT, quality);
    let chroma_table = scaled_table(&CHROMA_QUANT, quality);
    let tables = [
        Huffman::new(&DC_LUMA_BITS, &DC_VALUES),
        Huffman::new(&AC_LUMA_BITS, &AC_LUMA_VALUES),
        Huffman::new(&DC_CHROMA_BITS, &DC_VALUES),
        Huffman::new(&AC_CHROMA_BITS, &AC_CHROMA_VALUES),
    ];
    let mut out = Vec::with_capacity(width * height / 3 + 1024);
    headers(&mut out, width, height, color, &luma_table, &chroma_table);
    let mut encoder = Encoder {
        dct: dct_matrix(),
        writer: BitWriter { out, acc: 0, count: 0 },
        luma: Component::new(&luma_table, &tables[0], &tables[1]),
        chroma_blue: Component::new(&chroma_table, &tables[2], &tables[3]),
        chroma_red: Component::new(&chroma_table, &tables[2], &tables[3]),
    };
    // Les bords sont complétés en répétant la dernière ligne / colonne.
    let at = |x: usize, y: usize| (y.min(height - 1) * width + x.min(width - 1)) * channels;

    if !color {
        let mut block = [0f32; 64];
        for top in (0..height).step_by(8) {
            for left in (0..width).step_by(8) {
                for (i, sample) in block.iter_mut().enumerate() {
                    *sample = f32::from(pixels[at(left + i % 8, top + i / 8)]) - 128.0;
                }
                encoder.block(&block, 0);
            }
        }
    } else {
        let mut luma = [0f32; 256];
        let mut block = [0f32; 64];
        for top in (0..height).step_by(16) {
            for left in (0..width).step_by(16) {
                let mut blue = [0f32; 64];
                let mut red = [0f32; 64];
                for j in 0..16 {
                    for i in 0..16 {
                        let p = at(left + i, top + j);
                        let (r, g, b) = (f32::from(pixels[p]), f32::from(pixels[p + 1]), f32::from(pixels[p + 2]));
                        luma[j * 16 + i] = 0.299 * r + 0.587 * g + 0.114 * b - 128.0;
                        // Moyenne 2×2 : sous-échantillonnage 4:2:0.
                        let c = (j / 2) * 8 + i / 2;
                        blue[c] += 0.25 * (-0.168_736 * r - 0.331_264 * g + 0.5 * b);
                        red[c] += 0.25 * (0.5 * r - 0.418_688 * g - 0.081_312 * b);
                    }
                }
                for (bx, by) in [(0, 0), (8, 0), (0, 8), (8, 8)] {
                    for (i, sample) in block.iter_mut().enumerate() {
                        *sample = luma[(by + i / 8) * 16 + bx + i % 8];
                    }
                    encoder.block(&block, 0);
                }
                encoder.block(&blue, 1);
                encoder.block(&red, 2);
            }
        }
    }
    encoder.writer.flush();
    let mut out = encoder.writer.out;
    out.extend_from_slice(&[0xFF, 0xD9]); // EOI
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{collections::BTreeSet, io::Write, process::Command};

    #[test]
    fn zigzag_is_the_diagonal_scan() {
        let mut expected = Vec::new();
        for s in 0..15usize {
            let rows: Vec<usize> = (s.saturating_sub(7)..=s.min(7)).collect();
            // Diagonale paire : de bas en haut ; impaire : de haut en bas.
            let ordered: Vec<usize> = if s % 2 == 0 { rows.into_iter().rev().collect() } else { rows };
            expected.extend(ordered.into_iter().map(|row| row * 8 + (s - row)));
        }
        assert_eq!(ZIGZAG.to_vec(), expected);
    }

    #[test]
    fn huffman_tables_are_complete_prefix_codes() {
        let ac_symbols: BTreeSet<u8> = (0..16u8)
            .flat_map(|run| (1..=10u8).map(move |size| (run << 4) | size))
            .chain([0x00, 0xF0])
            .collect();
        for (bits, values) in [(&AC_LUMA_BITS, &AC_LUMA_VALUES), (&AC_CHROMA_BITS, &AC_CHROMA_VALUES)] {
            assert_eq!(bits.iter().map(|&b| b as usize).sum::<usize>(), values.len());
            assert_eq!(values.iter().copied().collect::<BTreeSet<u8>>(), ac_symbols);
        }
        for bits in [&DC_LUMA_BITS, &DC_CHROMA_BITS] {
            assert_eq!(bits.iter().map(|&b| b as usize).sum::<usize>(), DC_VALUES.len());
        }
        // Aucun code ne doit être préfixe d'un autre.
        let table = Huffman::new(&AC_LUMA_BITS, &AC_LUMA_VALUES);
        let codes: Vec<(u16, u8)> = AC_LUMA_VALUES.iter().map(|&s| (table.code[s as usize], table.size[s as usize])).collect();
        for (i, &(a, la)) in codes.iter().enumerate() {
            for &(b, lb) in &codes[i + 1..] {
                let shorter = la.min(lb);
                assert_ne!(a >> (la - shorter), b >> (lb - shorter), "préfixe commun");
            }
        }
    }

    #[test]
    fn categories_and_negative_values() {
        assert_eq!(category(0), 0);
        assert_eq!(category(1), 1);
        assert_eq!(category(-1), 1);
        assert_eq!(category(-3), 2);
        assert_eq!(category(1023), 10);
        assert_eq!(magnitude_bits(-1) & 1, 0);
        assert_eq!(magnitude_bits(-3) & 0b11, 0b00);
        assert_eq!(magnitude_bits(-2) & 0b11, 0b01);
    }

    #[test]
    fn stuffing_after_ff() {
        let mut writer = BitWriter { out: Vec::new(), acc: 0, count: 0 };
        writer.put(0xFFFF, 16);
        writer.put(0b1, 1);
        writer.flush();
        assert_eq!(writer.out, vec![0xFF, 0x00, 0xFF, 0x00, 0xFF, 0x00]);
    }

    #[test]
    fn quality_scaling_follows_libjpeg() {
        assert_eq!(scaled_table(&LUMA_QUANT, 50), LUMA_QUANT);
        assert_eq!(scaled_table(&LUMA_QUANT, 95)[0], 2);
        assert!(scaled_table(&LUMA_QUANT, 10).iter().all(|&q| q >= 50));
    }

    #[test]
    fn invalid_input_is_rejected() {
        assert!(encode(&[], 0, 0, 3, 50).is_err());
        assert!(encode(&[0; 10], 4, 4, 3, 50).is_err());
        assert!(encode(&[0; 32], 4, 4, 2, 50).is_err());
    }

    /// Image de test : dégradés doux + un disque, pour une mesure de PSNR.
    pub fn pattern(width: usize, height: usize, channels: usize) -> Vec<u8> {
        let mut pixels = Vec::with_capacity(width * height * channels);
        for y in 0..height {
            for x in 0..width {
                let dx = x as f32 - width as f32 / 2.0;
                let dy = y as f32 - height as f32 / 2.0;
                let disc = (dx * dx + dy * dy).sqrt() < height as f32 / 4.0;
                let r = (x * 255 / width.max(1)) as u8;
                let g = (y * 255 / height.max(1)) as u8;
                let b = if disc { 220 } else { 40 };
                if channels == 1 {
                    pixels.push(((u16::from(r) + u16::from(g) + u16::from(b)) / 3) as u8);
                } else {
                    pixels.extend_from_slice(&[r, g, b]);
                }
            }
        }
        pixels
    }

    /// Décodage indépendant par djpeg (libjpeg-turbo), installé dans l'image Docker.
    fn djpeg(jpeg: &[u8]) -> Option<(usize, usize, Vec<u8>)> {
        let mut child = Command::new("djpeg")
            .arg("-pnm")
            .stdin(std::process::Stdio::piped())
            .stdout(std::process::Stdio::piped())
            .stderr(std::process::Stdio::piped())
            .spawn()
            .ok()?;
        child.stdin.take().unwrap().write_all(jpeg).unwrap();
        let output = child.wait_with_output().unwrap();
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(output.status.success() && stderr.is_empty(), "djpeg : {stderr}");
        // En-tête PNM : P5|P6, largeur, hauteur, 255, puis les octets.
        let data = output.stdout;
        let mut fields = Vec::new();
        let mut position = 0;
        while fields.len() < 4 {
            while data[position].is_ascii_whitespace() {
                position += 1;
            }
            let start = position;
            while !data[position].is_ascii_whitespace() {
                position += 1;
            }
            fields.push(String::from_utf8_lossy(&data[start..position]).to_string());
        }
        let (width, height) = (fields[1].parse().unwrap(), fields[2].parse().unwrap());
        Some((width, height, data[position + 1..].to_vec()))
    }

    fn psnr(a: &[u8], b: &[u8]) -> f64 {
        let mse: f64 = a.iter().zip(b).map(|(&x, &y)| (f64::from(x) - f64::from(y)).powi(2)).sum::<f64>() / a.len() as f64;
        10.0 * (255.0f64 * 255.0 / mse.max(1e-9)).log10()
    }

    #[test]
    fn libjpeg_decodes_what_we_encode() {
        if Command::new("djpeg").arg("-version").output().is_err() {
            eprintln!("djpeg absent : test de décodage ignoré (il tourne dans Docker)");
            return;
        }
        // Tailles non multiples de 16, 1 pixel, gris et couleur.
        for (width, height, channels) in [(424, 240, 3), (37, 19, 3), (1, 1, 3), (64, 48, 1), (13, 7, 1)] {
            let pixels = pattern(width, height, channels);
            for quality in [MIN_QUALITY, 60, 90] {
                let jpeg = encode(&pixels, width, height, channels, quality).unwrap();
                let (w, h, decoded) = djpeg(&jpeg).unwrap();
                assert_eq!((w, h, decoded.len()), (width, height, pixels.len()));
                let score = psnr(&pixels, &decoded);
                // Seuils mesurés contre libjpeg (cjpeg) sur la même image : PSNR identique.
                // Une image minuscule perd plus au sous-échantillonnage de la couleur.
                let minimum = match (quality, width >= 64) {
                    (_, false) => 20.0,
                    (90, true) => 36.0,
                    (60, true) => 33.0,
                    _ => 27.0,
                };
                assert!(score > minimum, "{width}×{height}×{channels} q{quality} : PSNR {score:.1} dB");
            }
        }
    }

    #[test]
    fn flat_saturated_and_colored_images() {
        if Command::new("djpeg").arg("-version").output().is_err() {
            return;
        }
        // Blanc pur (octets 0xFF), noir, rouge pur : longues suites de zéros et couleurs extrêmes.
        for (rgb, width, height) in [([255u8, 255, 255], 40, 24), ([0, 0, 0], 16, 16), ([255, 0, 0], 33, 17)] {
            let pixels: Vec<u8> = rgb.iter().copied().cycle().take(width * height * 3).collect();
            let jpeg = encode(&pixels, width, height, 3, 75).unwrap();
            let (_, _, decoded) = djpeg(&jpeg).unwrap();
            for (channel, &expected) in rgb.iter().enumerate() {
                let mean = decoded.iter().skip(channel).step_by(3).map(|&v| f64::from(v)).sum::<f64>() / (width * height) as f64;
                assert!((mean - f64::from(expected)).abs() < 8.0, "{rgb:?} canal {channel} : {mean:.1}");
            }
        }
    }

    #[test]
    fn lower_quality_means_fewer_bytes() {
        let pixels = pattern(320, 240, 3);
        let small = encode(&pixels, 320, 240, 3, 30).unwrap().len();
        let large = encode(&pixels, 320, 240, 3, 90).unwrap().len();
        assert!(small < large, "{small} >= {large}");
        // Une image brute RVB 320×240 pèse 230 400 octets.
        assert!(large < 230_400 / 5, "{large}");
    }
}
