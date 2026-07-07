"""
SAP integration service (Phase 1 — mock implementation).

Provides the data-access layer for the autonomous SAP-connected RAG pipeline:
the catalog of SAP-exported Excel datasets (simulating OData $metadata) and
retrieval of individual datasets as pandas DataFrames.

MOCK MODE: no real SAP credentials exist yet, so both methods return
deterministic simulated data. The class boundary is the real one — when SAP
Gateway access arrives, only the two `_mock_*` internals change (replace with
pyodata / requests calls against SAP_BASE_URL using OAuth client credentials
from the environment); every caller (router, analyzer, endpoint) is untouched.

NOTE ON LOCATION: this repo uses a flat backend/ module layout and already has
a `services.py` MODULE, so a `backend/services/` package is not possible
without renaming that module and rewriting every import. New services live as
flat top-level modules by existing convention.
"""
import logging
import os
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger('procure_ai')

# Environment knobs for the eventual real integration — read now so deploy
# configs can be prepared ahead of the actual SAP connection.
SAP_BASE_URL = os.getenv('SAP_BASE_URL', '')          # e.g. https://sap-gw.corp/odata/v2
SAP_CLIENT_ID = os.getenv('SAP_CLIENT_ID', '')
SAP_CLIENT_SECRET = os.getenv('SAP_CLIENT_SECRET', '')


class SAPService:
    """Data-access layer for SAP-exported procurement datasets.

    Public contract (stable across mock → real migration):
      get_available_datasets() -> list[dict]   catalog with id/name/description
      fetch_dataset(dataset_id) -> pd.DataFrame
    """

    #: Simulated OData catalog. `description` is what the AI router reasons
    #: over, so descriptions are written the way a real metadata curator would.
    _MOCK_CATALOG: List[Dict] = [
        {
            'id': 'sap_001',
            'name': 'Q3_Vendor_Spend.xlsx',
            'description': 'Quarterly spend data for all IT vendors: vendor name, '
                           'category, PO count, total spend (USD), payment terms.',
            'system': 'SAP S/4HANA — MM',
            'last_updated': '2026-06-30',
        },
        {
            'id': 'sap_002',
            'name': 'Open_Purchase_Orders.xlsx',
            'description': 'All currently open purchase orders: PO number, vendor, '
                           'material, order value, delivery date, plant, status.',
            'system': 'SAP S/4HANA — MM',
            'last_updated': '2026-07-05',
        },
        {
            'id': 'sap_003',
            'name': 'Vendor_Master_Compliance.xlsx',
            'description': 'Vendor master records with compliance attributes: vendor '
                           'ID, name, country, risk rating, certifications, blocked flag.',
            'system': 'SAP S/4HANA — Vendor Master',
            'last_updated': '2026-06-28',
        },
        {
            'id': 'sap_004',
            'name': 'Inventory_Stock_Levels.xlsx',
            'description': 'Warehouse inventory positions: material, plant, storage '
                           'location, unrestricted stock, safety stock, stock value.',
            'system': 'SAP S/4HANA — WM',
            'last_updated': '2026-07-04',
        },
        {
            'id': 'sap_005',
            'name': 'Contract_Expiry_Register.xlsx',
            'description': 'Outline agreements and contracts with validity windows: '
                           'contract number, vendor, category, start/end date, value, '
                           'auto-renewal flag.',
            'system': 'SAP S/4HANA — Contract Mgmt',
            'last_updated': '2026-07-01',
        },
    ]

    def get_available_datasets(self) -> List[Dict]:
        """Return the catalog of SAP datasets available to the router.

        MOCK: returns the static catalog above. REAL: GET {SAP_BASE_URL}/$metadata,
        mapped into the same shape, cached with a short TTL.
        """
        logger.info(f'SAPService.get_available_datasets -> {len(self._MOCK_CATALOG)} datasets (mock)')
        return [dict(d) for d in self._MOCK_CATALOG]

    def get_dataset_meta(self, dataset_id: str) -> Optional[Dict]:
        """Catalog entry for one dataset id, or None if unknown."""
        return next((dict(d) for d in self._MOCK_CATALOG if d['id'] == dataset_id), None)

    def fetch_dataset(self, dataset_id: str) -> pd.DataFrame:
        """Fetch one dataset as a DataFrame.

        MOCK: deterministic generated frames (seeded per dataset id so repeat
        queries see identical data). REAL: OData $format=json entity fetch, or
        download of the staged Excel export, then pd.read_excel.

        Raises:
            KeyError: unknown dataset_id — callers surface an honest error,
                      never a silent empty frame.
        """
        if self.get_dataset_meta(dataset_id) is None:
            raise KeyError(f'Unknown SAP dataset id: {dataset_id!r}')

        rng = np.random.default_rng(abs(hash(dataset_id)) % (2 ** 32))
        builders = {
            'sap_001': self._mock_vendor_spend,
            'sap_002': self._mock_open_pos,
            'sap_003': self._mock_vendor_master,
            'sap_004': self._mock_inventory,
            'sap_005': self._mock_contracts,
        }
        df = builders[dataset_id](rng)
        logger.info(f'SAPService.fetch_dataset({dataset_id}) -> {len(df)} rows x {len(df.columns)} cols (mock)')
        return df

    # ── Mock dataset builders (replaced wholesale by the real OData client) ──

    @staticmethod
    def _mock_vendor_spend(rng) -> pd.DataFrame:
        vendors = ['TCS', 'Infosys', 'Wipro', 'IBM', 'Accenture', 'HCL', 'Capgemini', 'Cognizant']
        return pd.DataFrame({
            'Vendor': vendors,
            'Category': ['IT Services'] * 4 + ['Consulting'] * 2 + ['Cloud'] * 2,
            'PO_Count': rng.integers(3, 40, len(vendors)),
            'Total_Spend_USD': (rng.uniform(0.2, 4.5, len(vendors)) * 1_000_000).round(2),
            'Payment_Terms': rng.choice(['NET30', 'NET45', 'NET60'], len(vendors)),
        })

    @staticmethod
    def _mock_open_pos(rng) -> pd.DataFrame:
        n = 25
        return pd.DataFrame({
            'PO_Number': [f'45000{i:04d}' for i in range(1, n + 1)],
            'Vendor': rng.choice(['TCS', 'IBM', 'Dell', 'Lenovo', 'Cisco', 'HP'], n),
            'Material': rng.choice(['Laptop', 'Server', 'Switch', 'License', 'Support'], n),
            'Order_Value_USD': (rng.uniform(5, 250, n) * 1_000).round(2),
            'Delivery_Date': pd.date_range('2026-07-10', periods=n, freq='3D').strftime('%Y-%m-%d'),
            'Plant': rng.choice(['1000-Gurgaon', '2000-Chennai', '3000-HongKong'], n),
            'Status': rng.choice(['Open', 'Partially Delivered', 'Awaiting GR'], n),
        })

    @staticmethod
    def _mock_vendor_master(rng) -> pd.DataFrame:
        vendors = ['TCS', 'Infosys', 'Wipro', 'IBM', 'Accenture', 'HCL', 'Dell', 'Cisco', 'HP', 'Lenovo']
        return pd.DataFrame({
            'Vendor_ID': [f'V{i:05d}' for i in range(1, len(vendors) + 1)],
            'Vendor_Name': vendors,
            'Country': rng.choice(['India', 'USA', 'Germany', 'Singapore'], len(vendors)),
            'Risk_Rating': rng.choice(['Low', 'Medium', 'High'], len(vendors), p=[0.6, 0.3, 0.1]),
            'Certifications': rng.choice(['ISO9001', 'ISO27001', 'ISO9001;ISO27001', 'None'], len(vendors)),
            'Blocked': rng.choice([False, False, False, True], len(vendors)),
        })

    @staticmethod
    def _mock_inventory(rng) -> pd.DataFrame:
        n = 30
        return pd.DataFrame({
            'Material': [f'MAT-{i:04d}' for i in range(1, n + 1)],
            'Plant': rng.choice(['1000-Gurgaon', '2000-Chennai'], n),
            'Storage_Location': rng.choice(['SL01', 'SL02', 'SL03'], n),
            'Unrestricted_Stock': rng.integers(0, 500, n),
            'Safety_Stock': rng.integers(10, 100, n),
            'Stock_Value_USD': (rng.uniform(1, 80, n) * 1_000).round(2),
        })

    @staticmethod
    def _mock_contracts(rng) -> pd.DataFrame:
        n = 15
        starts = pd.date_range('2024-01-01', periods=n, freq='45D')
        return pd.DataFrame({
            'Contract_Number': [f'46000{i:04d}' for i in range(1, n + 1)],
            'Vendor': rng.choice(['TCS', 'Infosys', 'IBM', 'Accenture', 'Capgemini'], n),
            'Category': rng.choice(['IT Services', 'Consulting', 'Cloud', 'Hardware'], n),
            'Valid_From': starts.strftime('%Y-%m-%d'),
            'Valid_To': (starts + pd.Timedelta(days=730)).strftime('%Y-%m-%d'),
            'Contract_Value_USD': (rng.uniform(0.5, 8.0, n) * 1_000_000).round(2),
            'Auto_Renewal': rng.choice([True, False], n),
        })
