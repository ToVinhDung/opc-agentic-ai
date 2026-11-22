"""Build external TeamPack copies for upload-flow regression tests.

These helpers deliberately write into a caller-provided temporary directory.  No
prepared "complete" or "incomplete" workbook belongs in the release package.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook


BlankSpec = tuple[str, str, str, str]


def create_external_copy_with_blanks(
    source: Path,
    destination: Path,
    blanks: Iterable[BlankSpec],
) -> Path:
    """Copy ``source`` to ``destination`` and blank exact keyed fields.

    A blank spec is ``(sheet_name, key_field, key_value, target_field)``.  The
    function fails when a sheet/header/key is missing so a test can never pass
    after silently modifying the wrong cell.
    """

    workbook = load_workbook(source)
    for sheet_name, key_field, key_value, target_field in blanks:
        if sheet_name not in workbook.sheetnames:
            raise AssertionError(f"Missing fixture sheet: {sheet_name}")
        sheet = workbook[sheet_name]
        headers = {
            str(cell.value).strip(): cell.column
            for cell in sheet[1]
            if cell.value is not None and str(cell.value).strip()
        }
        if key_field not in headers or target_field not in headers:
            raise AssertionError(
                f"Missing fixture header in {sheet_name}: {key_field}/{target_field}"
            )
        matches = [
            row
            for row in range(2, sheet.max_row + 1)
            if str(sheet.cell(row, headers[key_field]).value).strip() == key_value
        ]
        if len(matches) != 1:
            raise AssertionError(
                f"Expected one {sheet_name}[{key_field}={key_value}], got {len(matches)}"
            )
        sheet.cell(matches[0], headers[target_field]).value = None

    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_external_copy_with_blanks(
        args.source,
        args.output,
        [("06_ORDERS", "order_id", "ORD-006", "estimated_cost")],
    )


if __name__ == "__main__":
    main()
