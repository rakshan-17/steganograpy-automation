"""
app.py
------
Flask backend for the Steganography Web Application.

Routes:
  GET  /                    – Serve the single-page UI
  POST /api/capacity        – Return image capacity info
  POST /api/encode/text     – Hide text inside an image
  POST /api/encode/file     – Hide a file inside an image
  POST /api/decode/text     – Extract hidden text from an image
  POST /api/decode/file     – Extract hidden file from an image
  GET  /api/download/<name> – Download a file from the outputs folder
"""

import os
import uuid
import logging
from pathlib import Path

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    abort,
)
from werkzeug.utils import secure_filename

from steganography import (
    calculate_capacity,
    encode_text,
    decode_text,
    encode_file,
    decode_file,
)

# ─── App Setup ────────────────────────────────────────────────────────────────

BASE_DIR    = Path(__file__).parent
UPLOAD_DIR  = BASE_DIR / "uploads"
OUTPUT_DIR  = BASE_DIR / "outputs"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg"}
ALLOWED_FILE_EXTENSIONS  = {"txt", "pdf", "zip", "docx", "csv", "json", "xml"}

MAX_IMAGE_SIZE = 20 * 1024 * 1024   # 20 MB
MAX_FILE_SIZE  = 10 * 1024 * 1024   # 10 MB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"]       = os.environ.get("SECRET_KEY", "stego-secret-change-in-prod")
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024   # hard Flask limit


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _allowed_image(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS
    )


def _allowed_file(filename: str) -> bool:
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_FILE_EXTENSIONS
    )


def _save_upload(file_storage, folder: Path, extra_suffix: str = "") -> Path:
    """
    Securely save an uploaded file with a UUID prefix.

    Args:
        file_storage: Werkzeug FileStorage object.
        folder:       Target directory.
        extra_suffix: Optional suffix to append before the extension.

    Returns:
        Path to the saved file.
    """
    original_name = secure_filename(file_storage.filename)
    ext  = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
    uid  = uuid.uuid4().hex
    name = f"{uid}{extra_suffix}.{ext}"
    path = folder / name
    file_storage.save(str(path))
    return path


def _error(message: str, code: int = 400):
    """Return a JSON error response."""
    logger.warning("API error %d: %s", code, message)
    return jsonify({"success": False, "error": message}), code


def _success(data: dict):
    """Return a JSON success response."""
    return jsonify({"success": True, **data})


def _cleanup(*paths):
    """Silently delete temporary files."""
    for p in paths:
        try:
            if p and os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass


def _human_bytes(n: int) -> str:
    """Format byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main single-page application."""
    return render_template("index.html")


@app.route("/api/capacity", methods=["POST"])
def api_capacity():
    """
    Return the steganographic capacity for an uploaded image.

    Form fields:
        image  – image file (required)
    """
    if "image" not in request.files:
        return _error("No image file provided.")

    img_file = request.files["image"]
    if not img_file.filename:
        return _error("No image selected.")
    if not _allowed_image(img_file.filename):
        return _error("Invalid image format. Use PNG or JPG.")

    img_path = _save_upload(img_file, UPLOAD_DIR)

    try:
        cap = calculate_capacity(str(img_path))
        return _success({
            "capacity_bytes": cap["capacity_bytes"],
            "capacity_human": _human_bytes(cap["capacity_bytes"]),
            "image_width":    cap["image_size"][0],
            "image_height":   cap["image_size"][1],
            "pixels":         cap["pixels"],
        })
    except Exception as exc:
        return _error(str(exc))
    finally:
        _cleanup(img_path)


@app.route("/api/encode/text", methods=["POST"])
def api_encode_text():
    """
    Hide a text message inside an image.

    Form fields:
        image    – carrier image (required)
        message  – secret text (required)
        password – AES password (optional)
    """
    if "image" not in request.files:
        return _error("No image file provided.")

    img_file = request.files["image"]
    message  = request.form.get("message", "").strip()
    password = request.form.get("password", "").strip()

    if not img_file.filename:
        return _error("No image selected.")
    if not _allowed_image(img_file.filename):
        return _error("Invalid image format. Use PNG or JPG.")
    if not message:
        return _error("Message must not be empty.")

    img_path  = _save_upload(img_file, UPLOAD_DIR)
    out_name  = f"{uuid.uuid4().hex}_stego.png"
    out_path  = OUTPUT_DIR / out_name

    try:
        result = encode_text(str(img_path), message, str(out_path), password)
        return _success({
            "download_url":    f"/api/download/{out_name}",
            "filename":        out_name,
            "payload_bytes":   result["payload_bytes"],
            "payload_human":   _human_bytes(result["payload_bytes"]),
            "capacity_bytes":  result["capacity_bytes"],
            "capacity_human":  _human_bytes(result["capacity_bytes"]),
            "remaining_bytes": result["remaining_bytes"],
            "remaining_human": _human_bytes(result["remaining_bytes"]),
            "encrypted":       bool(password),
        })
    except OverflowError as exc:
        return _error(str(exc))
    except Exception as exc:
        logger.exception("encode_text error")
        return _error(f"Encoding failed: {exc}", 500)
    finally:
        _cleanup(img_path)


@app.route("/api/encode/file", methods=["POST"])
def api_encode_file():
    """
    Hide a file inside an image.

    Form fields:
        image    – carrier image (required)
        file     – file to hide (required; txt/pdf/zip/docx/csv/json/xml)
        password – AES password (optional)
    """
    if "image" not in request.files:
        return _error("No image file provided.")
    if "file" not in request.files:
        return _error("No file to hide provided.")

    img_file   = request.files["image"]
    hide_file  = request.files["file"]
    password   = request.form.get("password", "").strip()

    if not img_file.filename:
        return _error("No image selected.")
    if not hide_file.filename:
        return _error("No file selected to hide.")
    if not _allowed_image(img_file.filename):
        return _error("Invalid image format. Use PNG or JPG.")
    if not _allowed_file(hide_file.filename):
        return _error(
            "Unsupported file type. Allowed: txt, pdf, zip, docx, csv, json, xml."
        )

    img_path  = _save_upload(img_file, UPLOAD_DIR)
    file_path = _save_upload(hide_file, UPLOAD_DIR)
    out_name  = f"{uuid.uuid4().hex}_stego.png"
    out_path  = OUTPUT_DIR / out_name

    # Rename saved upload to original filename (needed for metadata)
    original_name = secure_filename(hide_file.filename)
    named_path    = UPLOAD_DIR / f"{uuid.uuid4().hex}_{original_name}"
    os.rename(file_path, named_path)
    file_path = named_path

    try:
        result = encode_file(str(img_path), str(file_path), str(out_path), password)
        return _success({
            "download_url":    f"/api/download/{out_name}",
            "filename":        out_name,
            "file_size":       result["file_size"],
            "file_size_human": _human_bytes(result["file_size"]),
            "payload_bytes":   result["payload_bytes"],
            "payload_human":   _human_bytes(result["payload_bytes"]),
            "capacity_bytes":  result["capacity_bytes"],
            "capacity_human":  _human_bytes(result["capacity_bytes"]),
            "remaining_bytes": result["remaining_bytes"],
            "remaining_human": _human_bytes(result["remaining_bytes"]),
            "encrypted":       bool(password),
        })
    except OverflowError as exc:
        return _error(str(exc))
    except Exception as exc:
        logger.exception("encode_file error")
        return _error(f"File encoding failed: {exc}", 500)
    finally:
        _cleanup(img_path, file_path)


@app.route("/api/decode/text", methods=["POST"])
def api_decode_text():
    """
    Extract a hidden text message from a stego image.

    Form fields:
        image    – stego image (required)
        password – AES password (optional)
    """
    if "image" not in request.files:
        return _error("No image file provided.")

    img_file = request.files["image"]
    password = request.form.get("password", "").strip()

    if not img_file.filename:
        return _error("No image selected.")
    if not _allowed_image(img_file.filename):
        return _error("Invalid image format. Use PNG or JPG.")

    img_path = _save_upload(img_file, UPLOAD_DIR)

    try:
        message = decode_text(str(img_path), password)
        return _success({
            "message":        message,
            "message_length": len(message),
            "encrypted":      bool(password),
        })
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        logger.exception("decode_text error")
        return _error(f"Decoding failed: {exc}", 500)
    finally:
        _cleanup(img_path)


@app.route("/api/decode/file", methods=["POST"])
def api_decode_file():
    """
    Extract a hidden file from a stego image.

    Form fields:
        image    – stego image (required)
        password – AES password (optional)
    """
    if "image" not in request.files:
        return _error("No image file provided.")

    img_file = request.files["image"]
    password = request.form.get("password", "").strip()

    if not img_file.filename:
        return _error("No image selected.")
    if not _allowed_image(img_file.filename):
        return _error("Invalid image format. Use PNG or JPG.")

    img_path = _save_upload(img_file, UPLOAD_DIR)

    try:
        result   = decode_file(str(img_path), str(OUTPUT_DIR), password)
        out_name = os.path.basename(result["output_path"])
        return _success({
            "download_url":    f"/api/download/{out_name}",
            "filename":        result["filename"],
            "file_size":       result["file_size"],
            "file_size_human": _human_bytes(result["file_size"]),
            "encrypted":       bool(password),
        })
    except ValueError as exc:
        return _error(str(exc))
    except Exception as exc:
        logger.exception("decode_file error")
        return _error(f"File extraction failed: {exc}", 500)
    finally:
        _cleanup(img_path)


@app.route("/api/download/<filename>")
def api_download(filename: str):
    """
    Serve a file from the outputs directory.

    Path param:
        filename – name of the file inside outputs/

    Security: Only files directly inside outputs/ are served.
    """
    safe_name = secure_filename(filename)
    if not safe_name:
        abort(404)

    file_path = OUTPUT_DIR / safe_name
    if not file_path.is_file():
        abort(404)

    return send_file(str(file_path), as_attachment=True, download_name=safe_name)


# ─── Error Handlers ───────────────────────────────────────────────────────────

@app.errorhandler(413)
def too_large(_):
    return _error("Uploaded file is too large (max 30 MB total).", 413)


@app.errorhandler(404)
def not_found(_):
    return _error("Resource not found.", 404)


@app.errorhandler(500)
def server_error(_):
    return _error("Internal server error.", 500)


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
