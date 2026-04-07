# StegoCrypt — LSB Steganography Web App

> Hide text or files inside images. Optional AES-256 encryption.
> Built with Python 3.10+, Flask, Pillow, NumPy, pycryptodome.

---

## Project Structure

```
stego_app/
├── app.py               ← Flask backend (all API routes)
├── steganography.py     ← Core LSB encode / decode engine
├── crypto_utils.py      ← AES-256-CBC encrypt / decrypt (pycryptodome)
├── requirements.txt
├── README.md
├── templates/
│   └── index.html       ← Single-page UI
├── static/
│   ├── style.css
│   └── script.js
├── uploads/             ← Temp storage for incoming files
└── outputs/             ← Stego images & extracted files (served for download)
```

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.10 or newer |
| Flask | ≥ 3.0 |
| Pillow | ≥ 10.0 |
| NumPy | ≥ 1.26 |
| pycryptodome | ≥ 3.20 |
| Werkzeug | ≥ 3.0 (installed with Flask) |

---

## Installation

### Step 1 — Clone / copy the project

```bash
# If from git:
git clone https://github.com/yourname/stego_app.git
cd stego_app

# If from zip:
unzip stego_app.zip
cd stego_app
```

### Step 2 — Create and activate a virtual environment (recommended)

```bash
python3 -m venv venv

# macOS / Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Create required directories

```bash
mkdir -p uploads outputs
```

These are already included in the project but Git may not track empty folders.

### Step 5 — Run the application

```bash
python app.py
```

Open your browser at: **http://localhost:5000**

---

## Running in Production

For production, use Gunicorn instead of Flask's dev server:

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## Usage

### Encode — Hide text

1. Go to the **Encode** tab.
2. Upload a PNG or JPG carrier image.
3. The capacity bar shows how many bytes the image can hold.
4. Select **Text Message** mode.
5. Type your secret message.
6. (Optional) Enter a password for AES-256 encryption.
7. Click **Encode & Download** — save the stego image.

### Encode — Hide a file

1. Go to the **Encode** tab.
2. Upload a carrier image.
3. Select **File** mode.
4. Upload the file to hide (txt / pdf / zip / docx / csv / json / xml).
5. (Optional) Enter a password.
6. Click **Encode & Download**.

### Decode — Extract text

1. Go to the **Decode** tab.
2. Upload the stego image.
3. Select **Text** radio option.
4. Enter the password if it was encrypted.
5. Click **Decode** — the message appears on screen.

### Decode — Extract a file

1. Go to the **Decode** tab.
2. Upload the stego image.
3. Select **File** radio option.
4. Enter the password if it was encrypted.
5. Click **Decode** — download the recovered file.

---

## How Encoding Works (LSB)

Each pixel in an RGB image has three channels: Red, Green, Blue.
Each channel is stored as 1 byte (0–255).

LSB (Least Significant Bit) steganography replaces the last bit of each
channel value with one bit of the payload. This changes channel values
by at most ±1, which is **imperceptible to the human eye**.

```
Original pixel:  R=200 (11001000)  G=150 (10010110)  B=75 (01001011)
After hiding 3 bits (1, 0, 1):
Modified pixel:  R=201 (11001001)  G=150 (10010110)  B=75 (01001011)
                        ↑ bit set         ↑ unchanged      ↑ unchanged
```

### Payload format

```
[32-bit big-endian payload length header]
[N bytes of payload]
```

The 32-bit header lets the decoder know exactly how many bits to read.

For file embedding, the payload contains:

```
STEGO_FILE:<filename>\n<base64-encoded file bytes>###END_STEGO###
```

This metadata allows the original filename and file type to be restored.

---

## How File Embedding Works

1. Read the file as raw bytes.
2. Base64-encode the bytes (makes them ASCII-safe for the payload).
3. Prepend the header: `STEGO_FILE:<filename>\n`
4. Append the delimiter: `###END_STEGO###`
5. (Optional) AES-encrypt the entire payload.
6. Convert to a bit stream.
7. Write the 32-bit length, then each payload bit into the LSBs of the image pixels.
8. Save as PNG (lossless — required to preserve the data).

During extraction the steps are reversed.

---

## Capacity Calculation

```
capacity_bits  = width × height × 3
usable_bits    = capacity_bits - 32   (32 bits reserved for length header)
capacity_bytes = usable_bits / 8
```

Example: a 1920×1080 image can hold approximately **777 KB** of payload.

---

## Security Notes

| Feature | Implementation |
|---|---|
| Encryption | AES-256-CBC |
| Key derivation | PBKDF2-HMAC-SHA256, 200,000 iterations |
| Salt | 16 random bytes, unique per encode |
| IV | 16 random bytes, unique per encode |
| File traversal protection | `secure_filename()` + outputs-only serving |
| Upload validation | Extension whitelist + file size limits |

### Possible improvements

- Add HMAC authentication tag to detect tampering of the pixel data.
- Store a magic signature in pixel 0 to detect "no data" quickly.
- Support 2-LSB mode for double the capacity at slightly more visual noise.
- Add rate limiting (Flask-Limiter) to the API endpoints.
- Auto-delete outputs after 1 hour with a background scheduler (APScheduler).
- Use a proper secret key from environment variables in production.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'Crypto'` | Run `pip install pycryptodome` (not `pycrypto`) |
| `No module named 'PIL'` | Run `pip install Pillow` |
| `Address already in use` | Change port: `python app.py --port 5001` or kill the existing process |
| Image looks identical to original | That's expected — LSB changes are invisible |
| "No valid message found" on decode | You must decode the **stego output** image, not the original |
| "Decryption failed — wrong password" | The password must match exactly (case-sensitive) |
| File too large error | Use a bigger carrier image or a smaller file |
| JPG input | Automatically converted to PNG internally — always download the PNG output |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/capacity` | Get image capacity |
| POST | `/api/encode/text` | Hide text in image |
| POST | `/api/encode/file` | Hide file in image |
| POST | `/api/decode/text` | Extract hidden text |
| POST | `/api/decode/file` | Extract hidden file |
| GET  | `/api/download/<filename>` | Download output file |

All POST endpoints accept `multipart/form-data`.
All responses are JSON: `{"success": true, ...}` or `{"success": false, "error": "..."}`.

---

## License

MIT License — use freely, attribute appreciated.
