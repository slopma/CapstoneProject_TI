from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DataState(str, Enum):
    """Epistemic state of a discovered or analyzed data point."""
    OBSERVED = "observed"         # Dato obtenido directamente de osquery / recolector
    DERIVED = "derived"           # Dato calculado de forma determinista a partir de valores observados
    INFERRED = "inferred"         # Interpretación que depende de una hipótesis
    UNAVAILABLE = "unavailable"   # Dato que no se recopiló o que no pudo obtenerse
    ERROR = "error"               # Dato que falló al procesarse o en la consulta


class DataPointExplanation(BaseModel):
    """Structured explanation for a discovered resource or attribute."""
    id: str
    label: str
    what_is: str = Field(..., description="Definición comprensible del recurso o atributo")
    detected_value: Any = Field(None, description="Valor real proveniente del inventario")
    formatted_value: Optional[str] = Field(None, description="Representación legible del valor")
    interpretation: str = Field(..., description="Explicación concreta de lo que indica el dato")
    why_it_matters: str = Field(..., description="Relevancia para conocer la infraestructura")
    migration_relevance: str = Field(..., description="Cómo contribuye a evaluar una futura migración a AWS")
    provenance: str = Field(..., description="Tabla, campo o fuente de origen y fecha")
    state: DataState = Field(..., description="Estado epistémico: observed, derived, inferred, unavailable, error")
    limitations: str = Field(..., description="Qué no puede concluirse a partir de este dato")
    suggested_action: str = Field(..., description="Siguiente paso de validación recomendado")


class DiscoveryIssue(BaseModel):
    """Warning or non-fatal section error recorded during discovery parsing."""
    code: str
    severity: str = Field("warning", description="warning | error | info")
    section: str
    message: str
    provenance: str
    state: DataState = DataState.OBSERVED
    suggested_action: Optional[str] = None


class BaseDiscoveryCollectorParser(ABC):
    """Clean interface for multi-source discovery collectors (osquery, Open-AudIT, DB catalogs)."""

    collector_id: str = "base"
    collector_name: str = "Base Collector"
    supported_schemas: List[str] = []

    @abstractmethod
    def can_parse(self, raw_data: Dict[str, Any]) -> bool:
        """Return True if this parser supports the given JSON payload."""
        raise NotImplementedError

    @abstractmethod
    def validate_payload(self, raw_data: Any) -> List[str]:
        """Return a list of fatal validation error messages (empty if valid)."""
        raise NotImplementedError

    @abstractmethod
    def parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse and normalize the raw inventory into CloudMove's structured discovery contract."""
        raise NotImplementedError


class OpenAudITCollectorAdapter(BaseDiscoveryCollectorParser):
    """Prepared adapter interface for Open-AudIT device/network discovery JSON exports.

    Allows importing Open-AudIT inventories in future phases using the exact same
    CMIR bridge and UI sections without duplicating normalization logic.
    """

    collector_id = "open-audit"
    collector_name = "Open-AudIT Enterprise Discovery"
    supported_schemas = ["openaudit.device.v1", "cloudmove.openaudit.v1"]

    def can_parse(self, raw_data: Dict[str, Any]) -> bool:
        if not isinstance(raw_data, dict):
            return False
        schema = str(raw_data.get("schema_version") or "")
        source_tool = str((raw_data.get("source") or {}).get("tool") or "").lower()
        return schema in self.supported_schemas or source_tool in ("open-audit", "openaudit")

    def validate_payload(self, raw_data: Any) -> List[str]:
        if not isinstance(raw_data, dict):
            return ["El archivo de Open-AudIT debe ser un objeto JSON válido."]
        if not self.can_parse(raw_data):
            return ["Esquema de Open-AudIT no reconocido."]
        return []

    def parse(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError(
            "El conector Open-AudIT está preparado arquitectónicamente (OpenAudITCollectorAdapter), "
            "pero requiere un archivo de exportación de esquema 'cloudmove.openaudit.v1'."
        )


class DatabaseCatalogCollectorSpec(BaseModel):
    """Architectural contract for dedicated read-only database catalog collectors."""
    engine_id: str
    engine_name: str
    status: str = "prepared_interface"
    required_queries: List[str]
    target_aws_services: List[str]
    missing_in_osquery: List[str]


DATABASE_COLLECTOR_SPECS: Dict[str, DatabaseCatalogCollectorSpec] = {
    "postgresql": DatabaseCatalogCollectorSpec(
        engine_id="postgresql",
        engine_name="PostgreSQL Catalog Collector",
        status="prepared_interface",
        required_queries=[
            "SELECT datname, pg_database_size(datname) FROM pg_database;",
            "SELECT schemaname, count(*) FROM pg_tables GROUP BY schemaname;",
            "SELECT name, setting FROM pg_settings WHERE name IN ('server_version', 'max_connections', 'wal_level');",
            "SELECT extname, extversion FROM pg_extension;",
        ],
        target_aws_services=["Amazon RDS for PostgreSQL", "Amazon Aurora PostgreSQL", "AWS DMS"],
        missing_in_osquery=[
            "Listado de bases de datos, esquemas y tablas de usuario",
            "Tamaño real en disco por base de datos y tablespace",
            "Extensiones activas (PostGIS, pgvector, pg_stat_statements)",
            "Configuración de replicación lógica/física y conexiones concurrentes",
        ],
    ),
    "mysql": DatabaseCatalogCollectorSpec(
        engine_id="mysql",
        engine_name="MySQL / MariaDB Catalog Collector",
        status="prepared_interface",
        required_queries=[
            "SELECT table_schema, SUM(data_length + index_length) FROM information_schema.tables GROUP BY table_schema;",
            "SHOW GLOBAL VARIABLES WHERE Variable_name IN ('version', 'innodb_buffer_pool_size', 'binlog_format');",
            "SELECT engine, count(*) FROM information_schema.tables GROUP BY engine;",
        ],
        target_aws_services=["Amazon RDS for MariaDB", "Amazon RDS for MySQL", "Amazon Aurora MySQL", "AWS DMS"],
        missing_in_osquery=[
            "Esquemas de bases de datos, motores de almacenamiento (InnoDB vs MyISAM) y tamaño de índices",
            "Estado de binlog y topología de replicación",
            "Procedimientos almacenados, triggers y usuarios de base de datos",
        ],
    ),
    "sqlserver": DatabaseCatalogCollectorSpec(
        engine_id="sqlserver",
        engine_name="Microsoft SQL Server Catalog Collector",
        status="prepared_interface",
        required_queries=[
            "SELECT name, state_desc, recovery_model_desc, compatibility_level FROM sys.databases;",
            "SELECT DB_NAME(database_id), SUM(size)*8/1024 AS size_mb FROM sys.master_files GROUP BY database_id;",
            "SELECT SERVERPROPERTY('Edition'), SERVERPROPERTY('ProductVersion');",
        ],
        target_aws_services=["Amazon RDS for SQL Server", "EC2 con SQL Server (BYOL / License Included)", "AWS DMS"],
        missing_in_osquery=[
            "Edición (Enterprise, Standard, Express) para evaluación de licencias en AWS",
            "Bases de datos del sistema y de usuario, tamaños de MDF/LDF y nivel de compatibilidad",
            "Dependencias de SQL Server Agent, SSRS, SSIS, SSAS o Linked Servers",
        ],
    ),
}
