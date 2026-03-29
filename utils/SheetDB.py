# utils/SheetDB.py

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
from dotenv import load_dotenv

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

load_dotenv()

WhereType = Union[
    Dict[str, Any],             # equality on columns
    List[Tuple[str, str, Any]], # [(col, op, value), ...]
    Callable[[pd.Series], bool],# row predicate
    None,
]

@dataclass
class SheetDBConfig:
    spreadsheet_id: str
    sheet_name: str
    creds_json_path: Optional[str] = None
    header_row: int = 1  # 1-indexed

def load_service_account_from_env(prefix: str = "GOOGLE_SHEETS_") -> dict:
    fields = [
        "type", "project_id", "private_key_id", "private_key",
        "client_email", "client_id", "auth_uri", "token_uri",
        "auth_provider_x509_cert_url", "client_x509_cert_url"
    ]
    creds = {}
    for field in fields:
        env_name = f"{prefix}{field.upper()}"
        value = os.environ.get(env_name)
        if not value:
            raise RuntimeError(f"Missing required environment variable: {env_name}")
        if field == "private_key":
            value = value.replace("\\n", "\n")
        creds[field] = value
    return creds

class SheetDB:
    def __init__(self, config: SheetDBConfig):
        self.config = config
        self.gc = self._authorize(config)
        self.ws = self.gc.open_by_key(config.spreadsheet_id).worksheet(config.sheet_name)
        self._df: pd.DataFrame = pd.DataFrame()
        self._load_cache()

    # ------------------- Authorization -------------------
    @staticmethod
    def _authorize(config: SheetDBConfig):
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.readonly"
        ]
        if config.creds_json_path:
            creds = Credentials.from_service_account_file(config.creds_json_path, scopes=scopes)
            return gspread.authorize(creds)
        try:
            service_account_info = load_service_account_from_env()
            creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
            return gspread.authorize(creds)
        except RuntimeError as e:
            raise RuntimeError("No credentials found. Set GOOGLE_SHEETS_* env variables or provide creds_json_path.") from e

    # ------------------- Load & Sync -------------------
    def _load_cache(self) -> None:
        values = self.ws.get_all_values()
        if not values:
            self._df = pd.DataFrame()
            return
        header = values[self.config.header_row - 1]
        rows = values[self.config.header_row:]
        self._df = pd.DataFrame(rows, columns=header)
        self._df = self._df.apply(pd.to_numeric, errors="coerce").fillna(self._df)

    def refresh(self) -> None:
        self._load_cache()

    def commit(self) -> None:
        if self._df is None:
            return
        header = list(self._df.columns)
        data = self._df.astype(str).fillna("").values.tolist()
        self.ws.clear()
        self.ws.update(range_name="A1", values=[header] + data)

    # ------------------- Query Helpers -------------------
    @property
    def df(self) -> pd.DataFrame:
        return self._df.copy()

    def _mask_from_where(self, where: WhereType) -> pd.Series:
        if where is None:
            return pd.Series([True]*len(self._df), index=self._df.index)
        if callable(where):
            return self._df.apply(where, axis=1)
        if isinstance(where, dict):
            mask = pd.Series([True]*len(self._df), index=self._df.index)
            for col, val in where.items():
                if col not in self._df.columns:
                    raise KeyError(f"Column not found: {col}")
                mask &= (self._df[col] == val)
            return mask
        if isinstance(where, list):
            mask = pd.Series([True]*len(self._df), index=self._df.index)
            for col, op, val in where:
                if col not in self._df.columns:
                    raise KeyError(f"Column not found: {col}")
                series = self._df[col]
                if op == "==": mask &= (series == val)
                elif op == "!=": mask &= (series != val)
                elif op == ">": mask &= (pd.to_numeric(series, errors="coerce") > float(val))
                elif op == ">=": mask &= (pd.to_numeric(series, errors="coerce") >= float(val))
                elif op == "<": mask &= (pd.to_numeric(series, errors="coerce") < float(val))
                elif op == "<=": mask &= (pd.to_numeric(series, errors="coerce") <= float(val))
                elif op.lower() == "in":
                    if not isinstance(val, (list, tuple, set)):
                        raise ValueError("'in' operator requires iterable value")
                    mask &= series.isin(list(val))
                elif op.lower() == "contains": mask &= series.astype(str).str.contains(str(val), na=False)
                elif op.lower() == "startswith": mask &= series.astype(str).str.startswith(str(val), na=False)
                elif op.lower() == "endswith": mask &= series.astype(str).str.endswith(str(val), na=False)
                else: raise ValueError(f"Unsupported operator: {op}")
            return mask
        raise TypeError("Unsupported where type. Use dict, list of tuples, callable, or None.")

    # ------------------- CRUD -------------------
    def select(self, columns: Optional[Sequence[str]] = None, where: WhereType = None,
               order_by: Optional[str] = None, ascending: bool = True,
               limit: Optional[int] = None, offset: int = 0) -> pd.DataFrame:
        if self._df.empty:
            return self._df.copy()
        mask = self._mask_from_where(where)
        out = self._df[mask]
        if columns:
            for c in columns:
                if c not in out.columns:
                    raise KeyError(f"Column not found: {c}")
            out = out[list(columns)]
        if order_by:
            if order_by not in out.columns:
                raise KeyError(f"Column not found: {order_by}")
            out = out.sort_values(by=order_by, ascending=ascending, kind="stable")
        if offset:
            out = out.iloc[offset:]
        if limit is not None:
            out = out.iloc[:limit]
        return out.reset_index(drop=True)

    def insert(self, row: Dict[str, Any]) -> None:
        for key in row.keys():
            if key not in self._df.columns:
                self._df[key] = ""
        full_row = {col: row.get(col, "") for col in self._df.columns}
        self._df = pd.concat([self._df, pd.DataFrame([full_row])], ignore_index=True)

    def bulk_insert(self, rows: List[Dict[str, Any]]) -> int:
        if not rows: return 0
        all_keys = set()
        for row in rows: all_keys.update(row.keys())
        for key in all_keys:
            if key not in self._df.columns: self._df[key] = ""
        full_rows = [{col: row.get(col, "") for col in self._df.columns} for row in rows]
        new_df = pd.DataFrame(full_rows)
        self._df = pd.concat([self._df, new_df], ignore_index=True)
        return len(rows)

    def update(self, values: Dict[str, Any], where: WhereType = None) -> int:
        if not values: return 0
        mask = self._mask_from_where(where)
        count = int(mask.sum())
        for key in values.keys():
            if key not in self._df.columns: self._df[key] = ""
        for key, val in values.items():
            self._df.loc[mask, key] = val
        return count

    def batch_update(self, updates: List[Tuple[Dict[str, Any], WhereType]]) -> int:
        total_updated = 0
        for values, where in updates:
            total_updated += self.update(values, where)
        return total_updated

    def delete(self, where: WhereType = None) -> int:
        mask = self._mask_from_where(where)
        count = int(mask.sum())
        self._df = self._df.loc[~mask].reset_index(drop=True)
        return count

    # ------------------- Utilities -------------------
    def get_row_count(self) -> int: return len(self._df)
    def get_last_n_rows(self, n: int) -> pd.DataFrame: return self._df.tail(n).reset_index(drop=True)
    def row_exists(self, where: WhereType) -> bool: return self._mask_from_where(where).any()
    def get_column_values(self, column: str, unique: bool = False) -> List:
        if column not in self._df.columns: return []
        values = self._df[column].tolist()
        return list(set(values)) if unique else values
