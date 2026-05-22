import datetime
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Optional

from core.PR788_Preview import PreviewResult, measure_preview_and_save, preview_from_csv
from core.PR788_Utils import PR788
from serial.tools import list_ports


@dataclass
class MeasurementRecord:
    sequence_number: int
    next_sequence_number: int
    csv_path: str
    preview: PreviewResult


@dataclass
class SerialPortInfo:
    device: str
    description: str
    hwid: str

    @property
    def label(self) -> str:
        description = self.description.strip() or "Unknown device"
        return f"{self.device} - {description}"


@dataclass
class HistoryCsvItem:
    path: str
    name: str
    modified_timestamp: float


def build_timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d_%H.%M.%S.%f")


def list_serial_ports() -> List[SerialPortInfo]:
    ports = []
    for port in list_ports.comports():
        ports.append(
            SerialPortInfo(
                device=port.device,
                description=port.description or "",
                hwid=port.hwid or "",
            )
        )
    return ports


def list_history_csv_files(csv_dir: str) -> List[HistoryCsvItem]:
    directory = Path(csv_dir)
    if not csv_dir or not directory.exists() or not directory.is_dir():
        return []

    items: List[HistoryCsvItem] = []
    for csv_path in directory.glob("*.csv"):
        stat = csv_path.stat()
        items.append(
            HistoryCsvItem(
                path=str(csv_path),
                name=csv_path.name,
                modified_timestamp=stat.st_mtime,
            )
        )

    items.sort(key=lambda item: item.modified_timestamp, reverse=True)
    return items


def load_preview_from_csv(csv_path: str) -> PreviewResult:
    return preview_from_csv(csv_path)


def sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value.strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned.strip("._")


def render_filename_template(
    template: str,
    variables: Dict[str, object],
    extension: str = ".csv",
) -> str:
    normalized_template = template.strip() or "{counter}_{timestamp}"
    rendered = normalized_template.format_map(
        {key: sanitize_filename_part(str(value)) for key, value in variables.items()}
    )
    rendered = re.sub(r"[_-]{2,}", "_", rendered)
    rendered = rendered.strip("_-. ")
    rendered = sanitize_filename_part(rendered) or "measurement"
    if not rendered.lower().endswith(extension.lower()):
        rendered = f"{rendered}{extension}"
    return rendered


def build_template_variables(
    counter: Optional[int] = None,
    model: str = "",
    prefix: str = "",
    port: str = "",
    timestamp: Optional[str] = None,
) -> Dict[str, object]:
    resolved_timestamp = timestamp or build_timestamp()
    dt = datetime.datetime.strptime(resolved_timestamp, "%Y-%m-%d_%H.%M.%S.%f")
    return {
        "counter": "" if counter is None else counter,
        "timestamp": resolved_timestamp,
        "model": model,
        "prefix": prefix,
        "port": port,
        "date": dt.strftime("%Y-%m-%d"),
        "time": dt.strftime("%H.%M.%S"),
    }


def build_csv_name(
    sequence_number: int,
    timestamp: Optional[str] = None,
    suffix: str = "",
) -> str:
    resolved_timestamp = timestamp or build_timestamp()
    suffix_part = f"_{suffix}" if suffix else ""
    return f"{sequence_number}_{resolved_timestamp}{suffix_part}.csv"


def measure_with_name(
    pr788: PR788,
    csv_dir: str,
    csv_name: str,
    code: str = "5",
    expected_last_wavelength: int = 780,
    read_timeout: Optional[float] = None,
) -> PreviewResult:
    csv_path = str((Path(csv_dir) / csv_name))
    return measure_preview_and_save(
        pr788=pr788,
        csv_path=csv_path,
        code=code,
        expected_last_wavelength=expected_last_wavelength,
        read_timeout=read_timeout,
    )


def measure_with_template(
    pr788: PR788,
    csv_dir: str,
    template: str,
    code: str = "5",
    expected_last_wavelength: int = 780,
    read_timeout: Optional[float] = None,
    counter_value: Optional[int] = None,
    next_counter_value: Optional[int] = None,
) -> MeasurementRecord:
    variables = build_template_variables(
        counter=counter_value,
    )
    csv_name = render_filename_template(template, variables)
    preview = measure_with_name(
        pr788=pr788,
        csv_dir=csv_dir,
        csv_name=csv_name,
        code=code,
        expected_last_wavelength=expected_last_wavelength,
        read_timeout=read_timeout,
    )

    return MeasurementRecord(
        sequence_number=counter_value if counter_value is not None else -1,
        next_sequence_number=next_counter_value if next_counter_value is not None else -1,
        csv_path=preview.csv_path or str((Path(csv_dir) / csv_name)),
        preview=preview,
    )
