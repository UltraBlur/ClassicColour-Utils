import csv
import re
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import serial


PR788_DATA_PATTERN = re.compile(
    r"^\s*(\d{3}),([+-]?\d+(?:\.\d+)?e[+-]?\d+)\r\n",
    re.MULTILINE,
)


class PR788:
    """Minimal PR-788 serial utility for measurement and CSV export."""

    def __init__(
        self,
        serial_port_name: str = "COM3",
        baudrate: int = 9600,
        timeout: float = 1.0,
    ) -> None:
        self._serial_com = serial.Serial(
            port=serial_port_name,
            baudrate=baudrate,
            timeout=timeout,
        )

    def reconnect_serial(self) -> None:
        if self._serial_com.is_open:
            self._serial_com.close()
        self._serial_com.open()

    def ensure_open(self) -> None:
        if not self._serial_com.is_open:
            self._serial_com.open()

    def close_serial(self) -> None:
        if self._serial_com.is_open:
            self._serial_com.close()

    def _read_until_prompt(self, timeout: float = 2.0) -> bytes:
        deadline = time.monotonic() + timeout
        buffer = b""
        while time.monotonic() < deadline:
            chunk = self._serial_com.read(1)
            if not chunk:
                continue
            buffer += chunk
            if buffer.rstrip().endswith(b">"):
                return buffer
        raise TimeoutError("PR-788 did not return a prompt before timeout.")

    def remote_start(self, verify_prompt: bool = False, prompt_timeout: float = 2.0) -> bytes:
        self.reconnect_serial()
        self._serial_com.write(b"P")
        self._serial_com.write(b"H")
        self._serial_com.write(b"O")
        self._serial_com.write(b"T")
        self._serial_com.write(b"O")
        time.sleep(0.2)
        self._serial_com.write(b"E1\r\n")
        if verify_prompt:
            return self._read_until_prompt(timeout=prompt_timeout)
        return b""

    def remote_terminate(self) -> None:
        self.ensure_open()
        self._serial_com.write(b"Q")

    def measure(
        self,
        code: str = "5",
        expected_last_wavelength: int = 780,
        read_timeout: Optional[float] = None,
    ) -> bytes:
        """
        Trigger a measurement and return the raw serial response.

        The default command matches the original script: ``M5\\r\\n``.
        """
        self._serial_com.reset_input_buffer()
        self._serial_com.write(f"M{code}\r\n".encode("ascii"))

        serial_data_all = b""
        deadline = None if read_timeout is None else time.monotonic() + read_timeout
        end_marker = re.compile(
            rf"^\s*{expected_last_wavelength},[^\r\n]+\r\n>",
            re.MULTILINE,
        )

        while True:
            chunk = self._serial_com.read(1)
            if not chunk:
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("Timed out while waiting for PR-788 measurement data.")
                continue

            serial_data_all += chunk
            decoded = serial_data_all.decode("utf-8", errors="ignore")
            if end_marker.search(decoded):
                return serial_data_all

    @staticmethod
    def parse_measurement_bytes(byte_data: bytes) -> List[Tuple[int, float]]:
        """Extract ``(wavelength, value)`` pairs from the PR-788 response."""
        decoded = byte_data.decode("utf-8", errors="strict")
        rows = PR788_DATA_PATTERN.findall(decoded)
        if not rows:
            raise ValueError("No spectral data was found in the PR-788 response.")

        return [(int(wavelength), float(value)) for wavelength, value in rows]

    @staticmethod
    def save_csv(rows: Sequence[Tuple[int, float]], csv_path: str) -> Path:
        """Save parsed PR-788 rows to a two-column CSV file."""
        output_path = Path(csv_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerows(rows)

        return output_path

    def measure_to_csv(
        self,
        csv_path: str,
        code: str = "5",
        expected_last_wavelength: int = 780,
        read_timeout: Optional[float] = None,
    ) -> Path:
        """Measure once and save the result directly as CSV."""
        raw_bytes = self.measure(
            code=code,
            expected_last_wavelength=expected_last_wavelength,
            read_timeout=read_timeout,
        )
        rows = self.parse_measurement_bytes(raw_bytes)
        return self.save_csv(rows, csv_path)
