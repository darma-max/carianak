# IDX Subsidiary Counter

Skrip Python untuk mengekstrak dan menghitung anak perusahaan dari tabel **“Informasi mengenai anak perusahaan Perseroan”** pada PDF laporan keuangan e-reporting IDX/OJK. Skrip memvalidasi nomor urut dan menghasilkan ringkasan, CSV, serta JSON.

## Prasyarat

- Python 3.8 atau lebih baru.
- `pdftotext` dari Poppler agar teks tabel dapat diekstrak. Pastikan perintah `pdftotext` tersedia di terminal:
  - **Windows:** instal Poppler, misalnya dengan `winget install --id oschwartz10612.Poppler -e`, lalu buka terminal baru dan jalankan `pdftotext -v`.
  - **macOS:** `brew install poppler`.
  - **Debian/Ubuntu:** `sudo apt update && sudo apt install poppler-utils`.

Skrip memakai pustaka standar Python dan tidak memerlukan instalasi paket Python untuk jalur utama. Jika `pdftotext` tidak tersedia atau tidak dapat membaca PDF, skrip mencoba memakai `pdfplumber` sebagai cadangan. Ini opsional: instal dengan `python -m pip install pdfplumber` (atau `py -m pip install pdfplumber` di Windows).

## Penggunaan

1. Clone repository dan masuk ke foldernya:

   ```sh
   git clone https://github.com/darma-max/carianak.git
   cd carianak
   ```

2. Salin PDF laporan ke folder `input/`, misalnya `input/FinancialStatement-2023-Tahunan-AALI.pdf`. PDF input dan file hasil di `output/` tidak dilacak Git.

3. Jalankan skrip dari root repository:

   **Windows (PowerShell atau Command Prompt):**

   ```powershell
   py scripts\count_subsidiaries.py "input\FinancialStatement-2023-Tahunan-AALI.pdf" --out-dir output
   ```

   **macOS/Linux:**

   ```sh
   python3 scripts/count_subsidiaries.py "input/FinancialStatement-2023-Tahunan-AALI.pdf" --out-dir output
   ```

   Untuk menambah istilah kegiatan usaha yang belum dikenali, berikan daftar dipisah koma:

   ```sh
   python scripts/count_subsidiaries.py "input/laporan.pdf" --out-dir output --extra-activities "Batubara,Jasa Keuangan"
   ```

4. Baca ringkasan Markdown di terminal. Hasil terstruktur disimpan sebagai `output/subsidiaries.csv` dan `output/subsidiaries.json`. Isi folder `output/` akan dibuat otomatis bila belum ada. Jika menjalankan skrip tanpa `--out-dir`, hasil ditulis ke direktori kerja saat ini.

## Exit code dan peringatan

| Kode | Arti |
|---|---|
| `0` | Tabel ditemukan dan validasi bersih. |
| `2` | Tabel standar tidak ditemukan atau tidak ada baris yang cocok pola. Gunakan fallback pada spesifikasi skill untuk memeriksa format PDF, OCR, atau hitung manual dengan menyebut sumbernya. |
| `3` | Tabel ditemukan, tetapi ada peringatan validasi. Jumlah tetap tersedia; periksa peringatan di ringkasan dan JSON, lalu sampaikan anomali yang relevan. |

Selain itu, kegagalan ekstraksi PDF ditampilkan sebagai error. Pastikan PDF dapat dibaca dan `pdftotext` atau pustaka fallback tersedia. Skrip tidak mengubah data sumber secara diam-diam; misalnya, perbedaan satuan aset dilaporkan sebagai peringatan.

## Batasan hitungan

Jumlah yang dilaporkan adalah jumlah baris anak perusahaan dalam tabel pada surat penyampaian laporan ke IDX, bukan daftar anak langsung/tidak langsung dari catatan konsolidasian. Jumlah aset anak perusahaan juga bukan total aset konsolidasi. PDF hasil pindai mungkin memerlukan OCR terlebih dahulu; PDF yang tidak memakai format e-reporting standar dapat membutuhkan pemeriksaan manual.
