# kgfoundry_common.settings

Typed runtime configuration with fail-fast validation

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/settings.py)

## Hierarchy

- **Parent:** [kgfoundry_common](../kgfoundry_common.md)

## Sections

- **Public API**

## Contents

### kgfoundry_common.settings.FaissConfig

::: kgfoundry_common.settings.FaissConfig

*Bases:* BaseSettings

### kgfoundry_common.settings.ObservabilityConfig

::: kgfoundry_common.settings.ObservabilityConfig

*Bases:* BaseSettings

### kgfoundry_common.settings.RuntimeSettings

::: kgfoundry_common.settings.RuntimeSettings

*Bases:* BaseSettings

### kgfoundry_common.settings.SearchConfig

::: kgfoundry_common.settings.SearchConfig

*Bases:* BaseSettings

### kgfoundry_common.settings.SparseEmbeddingConfig

::: kgfoundry_common.settings.SparseEmbeddingConfig

*Bases:* BaseSettings

### kgfoundry_common.settings.load_settings

::: kgfoundry_common.settings.load_settings

## Relationships

**Imports:** `__future__.annotations`, `kgfoundry_common.errors.SettingsError`, `kgfoundry_common.logging.get_logger`, `kgfoundry_common.navmap_loader.load_nav_metadata`, `kgfoundry_common.typing.gate_import`, `pydantic.Field`, `pydantic_settings.BaseSettings`, `pydantic_settings.SettingsConfigDict`, `typing.Any`, `typing.ClassVar`, `typing.TYPE_CHECKING`, `typing.cast`

## Autorefs Examples

- [kgfoundry_common.settings.FaissConfig][]
- [kgfoundry_common.settings.ObservabilityConfig][]
- [kgfoundry_common.settings.RuntimeSettings][]
- [kgfoundry_common.settings.load_settings][]

## Inheritance

```mermaid
classDiagram
    class FaissConfig
    class BaseSettings
    BaseSettings <|-- FaissConfig
    class ObservabilityConfig
    BaseSettings <|-- ObservabilityConfig
    class RuntimeSettings
    BaseSettings <|-- RuntimeSettings
    class SearchConfig
    BaseSettings <|-- SearchConfig
    class SparseEmbeddingConfig
    BaseSettings <|-- SparseEmbeddingConfig
```

## Neighborhood

```d2
direction: right
"kgfoundry_common.settings": "kgfoundry_common.settings" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/settings.py" }
"__future__.annotations": "__future__.annotations"
"kgfoundry_common.settings" -> "__future__.annotations"
"kgfoundry_common.errors.SettingsError": "kgfoundry_common.errors.SettingsError"
"kgfoundry_common.settings" -> "kgfoundry_common.errors.SettingsError"
"kgfoundry_common.logging.get_logger": "kgfoundry_common.logging.get_logger"
"kgfoundry_common.settings" -> "kgfoundry_common.logging.get_logger"
"kgfoundry_common.navmap_loader.load_nav_metadata": "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.settings" -> "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.typing.gate_import": "kgfoundry_common.typing.gate_import"
"kgfoundry_common.settings" -> "kgfoundry_common.typing.gate_import"
"pydantic.Field": "pydantic.Field"
"kgfoundry_common.settings" -> "pydantic.Field"
"pydantic_settings.BaseSettings": "pydantic_settings.BaseSettings"
"kgfoundry_common.settings" -> "pydantic_settings.BaseSettings"
"pydantic_settings.SettingsConfigDict": "pydantic_settings.SettingsConfigDict"
"kgfoundry_common.settings" -> "pydantic_settings.SettingsConfigDict"
"typing.Any": "typing.Any"
"kgfoundry_common.settings" -> "typing.Any"
"typing.ClassVar": "typing.ClassVar"
"kgfoundry_common.settings" -> "typing.ClassVar"
"typing.TYPE_CHECKING": "typing.TYPE_CHECKING"
"kgfoundry_common.settings" -> "typing.TYPE_CHECKING"
"typing.cast": "typing.cast"
"kgfoundry_common.settings" -> "typing.cast"
"kgfoundry_common": "kgfoundry_common" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/kgfoundry_common/__init__.py" }
"kgfoundry_common" -> "kgfoundry_common.settings" { style: dashed }
```

