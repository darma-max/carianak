#!/usr/bin/env python3
"""
Deteksi dan hitung anak perusahaan dari PDF laporan keuangan emiten Indonesia
(format e-reporting IDX/XBRL: tabel "Informasi mengenai anak perusahaan Perseroan sebagai berikut").

Pemakaian:
    python count_subsidiaries.py <file.pdf> [--out-dir DIR] [--extra-activities "Batubara,Jasa"]

Keluaran:
    - ringkasan Markdown ke stdout
    - <out-dir>/subsidiaries.csv  dan  <out-dir>/subsidiaries.json
Exit code 0 = tabel ditemukan & lolos validasi, 2 = tabel tidak ditemukan, 3 = ditemukan tapi ada peringatan validasi.
"""
import argparse, csv, json, re, subprocess, sys, os
from collections import Counter, OrderedDict

UNIT_MULT = {"SATUAN": 1, "RIBUAN": 1e3, "JUTAAN": 1e6, "MILIARAN": 1e9, "TRILIUNAN": 1e12,
             "RIBU": 1e3, "JUTA": 1e6, "MILIAR": 1e9, "TRILIUN": 1e12}

PROVINCES = [
    "Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Kepulauan Riau", "Jambi", "Sumatera Selatan",
    "Bangka Belitung", "Kepulauan Bangka Belitung", "Bengkulu", "Lampung", "DKI Jakarta", "Jakarta",
    "Banten", "Jawa Barat", "Jawa Tengah", "DI Yogyakarta", "Yogyakarta", "Jawa Timur", "Bali",
    "Nusa Tenggara Barat", "Nusa Tenggara Timur", "Kalimantan Barat", "Kalimantan Tengah",
    "Kalimantan Selatan", "Kalimantan Timur", "Kalimantan Utara", "Sulawesi Utara", "Gorontalo",
    "Sulawesi Tengah", "Sulawesi Selatan", "Sulawesi Tenggara", "Sulawesi Barat", "Maluku",
    "Maluku Utara", "Papua", "Papua Barat", "Papua Barat Daya", "Papua Selatan", "Papua Tengah",
    "Papua Pegunungan",
    # luar negeri yang sering muncul
    "Singapura", "Malaysia", "Hong Kong", "Hongkong", "Belanda", "Mauritius", "Cayman Islands",
    "British Virgin Islands", "Thailand", "Filipina", "Vietnam", "Tiongkok", "China", "Australia",
    "Amerika Serikat", "Inggris", "India", "Jepang", "Korea Selatan", "Kamboja", "Myanmar",
]
ACTIVITIES = [
    "Kelapa Sawit", "Penyulingan Minyak", "Karet", "Lainnya", "Perkebunan", "Pertambangan", "Batubara",
    "Perdagangan", "Jasa", "Properti", "Real Estat", "Konstruksi", "Perbankan", "Asuransi", "Pembiayaan",
    "Telekomunikasi", "Energi", "Industri", "Manufaktur", "Holding", "Investasi", "Transportasi",
    "Pembangkit Listrik", "Kakao", "Kopi", "Teh", "Tebu", "Kehutanan", "Perikanan", "Peternakan",
    "Pengolahan", "Pabrik", "Distribusi", "Logistik", "Teknologi", "Perhotelan", "Rumah Sakit",
    "Minyak dan Gas", "Pertanian", "Pupuk", "Semen", "Baja",
]

HEADER_RE = re.compile(
    r"No\s+Nama\s+Kegiatan\s+Usaha\s+Lokasi\s+Tahun\s+Komersil\s+Status\s+Operasi\s+"
    r"Jumlah\s+Aset\s+Satuan\s+Mata\s+Uang\s+Persentase\s+\(%\)", re.I)
# header versi pdfplumber (kolom bergeser) -> longgar
HEADER_LOOSE_RE = re.compile(r"No\s+Nama\s+Kegiatan.*?Persentase\s*\(%\)", re.I | re.S)
FOOTER_RE = re.compile(r"Dokumen ini merupakan dokumen resmi.*?dalam dokumen ini\.", re.I | re.S)
SECTION_END_RE = re.compile(r"\[\d{6,7}[A-Za-z_]*\]")  # awal sheet XBRL berikutnya, mis. [1000000]
SECTION_START_RE = re.compile(r"anak\s+perusahaan", re.I)

TAIL_RE = re.compile(
    r"(?<!\S)(?P<year>\d{4}|-)\s+(?P<status>[A-Za-z][A-Za-z ]*?)\s+"
    r"(?P<asset>-?\d[\d.,]*)\s+(?P<unit>[A-Z]{4,})\s+(?P<cur>[A-Z]{3})\s+(?P<pct>\d+(?:[.,]\d+)?)")


def extract_text(path):
    """pdftotext -raw menjaga urutan baris-per-baris tabel; pdfplumber sebagai cadangan."""
    try:
        out = subprocess.run(["pdftotext", "-raw", path, "-"], capture_output=True, text=True, timeout=180)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout, "pdftotext -raw"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join((p.extract_text() or "") for p in pdf.pages), "pdfplumber"
    except Exception as e:  # noqa
        sys.exit(f"Gagal mengekstrak teks dari PDF: {e}")


def parse_idr_number(s):
    s = s.strip()
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):      # 1.546.701 / 1.546.701,5
        return float(s.replace(".", "").replace(",", "."))
    if re.fullmatch(r"-?\d+,\d+", s):                        # 12,5
        return float(s.replace(",", "."))
    return float(s.replace(",", ""))                         # 842 / 99.99 / 1,234 (en)


def parse_pct(s):
    return float(s.replace(",", "."))


def _flex(phrase):
    return r"\s+".join(map(re.escape, phrase.split()))


def split_head(head, activities, provinces):
    """head = 'PT Waru Kaltim Plantation Kelapa Sawit Kalimantan Timur' -> (nama, kegiatan, lokasi)"""
    head = re.sub(r"\s+", " ", head).strip()
    lokasi = kegiatan = None
    for p in sorted(provinces, key=len, reverse=True):
        m = re.search(r"(?:^|\s)(" + _flex(p) + r")$", head, re.I)
        if m:
            lokasi = p; head = head[:m.start(1)].strip(); break
    for a in sorted(activities, key=len, reverse=True):
        m = re.search(r"(?:^|\s)(" + _flex(a) + r")$", head, re.I)
        if m:
            kegiatan = a; head = head[:m.start(1)].strip(); break
    return head, kegiatan, lokasi


def locate_section(text):
    """Kembalikan teks tabel anak perusahaan (setelah header pertama) atau None."""
    m = SECTION_START_RE.search(text)
    start_search = m.start() if m else 0
    hm = HEADER_RE.search(text, start_search) or HEADER_LOOSE_RE.search(text, start_search)
    if not hm:
        return None
    body = text[hm.end():]
    em = SECTION_END_RE.search(body)
    if em:
        body = body[:em.start()]
    body = FOOTER_RE.sub("\n", body)
    body = HEADER_RE.sub("\n", body)
    body = HEADER_LOOSE_RE.sub("\n", body)
    return body


def parse_records(body, activities, provinces):
    records, pos = [], 0
    for m in TAIL_RE.finditer(body):
        head = body[pos:m.start()]
        pos = m.end()
        hm = re.match(r"\s*(\d{1,4})\s+(.*)", head, re.S)
        if not hm:
            records.append({"_error": f"baris tanpa nomor urut: {head.strip()[:80]!r}"}); continue
        no, head_text = int(hm.group(1)), hm.group(2)
        nama, kegiatan, lokasi = split_head(head_text, activities, provinces)
        unit = m["unit"].upper()
        asset = parse_idr_number(m["asset"])
        mult = UNIT_MULT.get(unit)
        notes = []
        if kegiatan is None: notes.append("kegiatan usaha tidak dikenali (cek manual / pakai --extra-activities)")
        if lokasi is None: notes.append("lokasi tidak dikenali (cek manual)")
        if re.search(r"\s[a-z]{1,3}$", nama): notes.append("nama kemungkinan terpotong di pergantian baris")
        records.append(OrderedDict(
            no=no, nama=nama, kegiatan_usaha=kegiatan, lokasi=lokasi,
            tahun_komersil=None if m["year"] == "-" else int(m["year"]),
            status_operasi=m["status"].strip(), jumlah_aset=asset, satuan=unit, mata_uang=m["cur"],
            aset_dalam_mata_uang_penuh=(asset * mult) if mult else None,
            persentase_kepemilikan=parse_pct(m["pct"]), catatan="; ".join(notes)))
    leftover = body[pos:].strip()
    return records, leftover


def validate(records, leftover):
    warns = []
    nos = [r["no"] for r in records if "no" in r]
    if nos != list(range(1, len(nos) + 1)):
        missing = sorted(set(range(1, (max(nos) if nos else 0) + 1)) - set(nos))
        warns.append(f"Nomor urut tidak berurutan 1..{len(nos)}; hilang/duplikat: {missing or 'duplikat'}")
    names = Counter(r["nama"].lower() for r in records if "nama" in r)
    dup = [n for n, c in names.items() if c > 1]
    if dup: warns.append(f"Nama ganda: {dup}")
    if leftover and re.search(r"\d", leftover):
        warns.append(f"Ada teks sisa setelah baris terakhir yang mengandung angka (mungkin baris gagal di-parse): {leftover[:120]!r}")
    units = Counter(r["satuan"] for r in records if "satuan" in r)
    if len(units) > 1:
        modal = units.most_common(1)[0][0]
        odd = [f"#{r['no']} {r['nama']} ({r['satuan']})" for r in records if r.get("satuan") != modal]
        warns.append(f"Satuan tidak seragam (mayoritas {modal}): {', '.join(odd)} - kemungkinan salah input emiten, JANGAN dikoreksi diam-diam")
    curs = Counter(r["mata_uang"] for r in records if "mata_uang" in r)
    if len(curs) > 1: warns.append(f"Mata uang campuran: {dict(curs)}")
    return warns


def meta(text):
    g = lambda label: (re.search(label + r"\s+(.+)", text) or [None, None])[1]
    return {"nama_emiten": g(r"Nama Emiten"), "kode_emiten": g(r"Kode Emiten"),
            "periode": (re.search(r"berakhir pada (\d{2}/\d{2}/\d{4})", text) or [None, None])[1]}


def fmt_idr(v):
    return f"Rp{v/1e12:,.2f} triliun" if v >= 1e12 else f"Rp{v/1e9:,.1f} miliar"


def summarize(records, m, warns, method):
    rs = [r for r in records if "no" in r]
    n = len(rs)
    L = [f"# Anak perusahaan {m['nama_emiten'] or '(emiten?)'} ({m['kode_emiten'] or '-'}) - periode {m['periode'] or '-'}", "",
         f"**Jumlah anak perusahaan: {n}**  _(ekstraksi: {method}; tabel 'Informasi mengenai anak perusahaan')_", ""]
    def table(title, counter):
        L.append(f"**{title}**"); L.append("")
        L.append("| Kategori | Jumlah |"); L.append("|---|---|")
        for k, v in counter.most_common(): L.append(f"| {k} | {v} |")
        L.append("")
    table("Status operasi", Counter(r["status_operasi"] for r in rs))
    table("Kegiatan usaha", Counter(r["kegiatan_usaha"] or "(tidak dikenali)" for r in rs))
    table("Lokasi", Counter(r["lokasi"] or "(tidak dikenali)" for r in rs))
    def bucket(p):
        return "100% / >=99.99%" if p >= 99.99 else ("95% - <99.99%" if p >= 95 else ("50% - <95%" if p >= 50 else "<50%"))
    table("Kepemilikan Perseroan", Counter(bucket(r["persentase_kepemilikan"]) for r in rs))
    partial = [r for r in rs if r["persentase_kepemilikan"] < 99.99]
    if partial:
        L.append("Kepemilikan < 99.99%: " + "; ".join(f"{r['nama']} ({r['persentase_kepemilikan']:g}%)" for r in partial)); L.append("")
    tot = sum(r["aset_dalam_mata_uang_penuh"] or 0 for r in rs)
    L.append(f"Total aset seluruh anak perusahaan (sesuai satuan masing-masing, belum eliminasi intra-grup): {fmt_idr(tot)} "
             "- bukan pengganti total aset konsolidasi.")
    L.append("")
    if warns:
        L.append("**Peringatan validasi**"); L.append("")
        L += [f"- {w}" for w in warns]; L.append("")
    flagged = [r for r in rs if r["catatan"]]
    if flagged:
        L.append("**Catatan per baris**"); L.append("")
        L += [f"- #{r['no']} {r['nama']}: {r['catatan']}" for r in flagged]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf"); ap.add_argument("--out-dir", default=".")
    ap.add_argument("--extra-activities", default="", help="daftar kegiatan usaha tambahan, dipisah koma")
    a = ap.parse_args()
    activities = ACTIVITIES + [x.strip() for x in a.extra_activities.split(",") if x.strip()]
    text, method = extract_text(a.pdf)
    body = locate_section(text)
    if body is None:
        print("TABEL ANAK PERUSAHAAN TIDAK DITEMUKAN pada format e-reporting standar. Lihat bagian 'Fallback' di SKILL.md.")
        sys.exit(2)
    records, leftover = parse_records(body, activities, PROVINCES)
    if not records:
        print("Header tabel ditemukan tetapi tidak ada baris yang cocok pola. Lihat 'Fallback' di SKILL.md.")
        sys.exit(2)
    warns = validate(records, leftover)
    m = meta(text)
    os.makedirs(a.out_dir, exist_ok=True)
    rs = [r for r in records if "no" in r]
    with open(os.path.join(a.out_dir, "subsidiaries.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rs[0].keys())); w.writeheader(); w.writerows(rs)
    with open(os.path.join(a.out_dir, "subsidiaries.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": m, "jumlah_anak_perusahaan": len(rs), "peringatan": warns, "anak_perusahaan": rs}, f, ensure_ascii=False, indent=2)
    print(summarize(records, m, warns, method))
    sys.exit(3 if warns else 0)


if __name__ == "__main__":
    main()
