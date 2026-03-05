module.exports = {
    schema: {
        "tableName": "escaneos",
        "columns": {
            "id": {
                "type": "UUID_V7",
                "allowNull": false,
                "nullable": false,
                "required": true,
                "primaryKey": true,
                "default": "gen_random_uuid_v7()"
            },
            "activo_id": {
                "type": "UUID_V7",
                "allowNull": false,
                "nullable": false,
                "required": true,
                "foreignKey": {
                    "table": "infra.activos",
                    "column": "id",
                    "onDelete": "CASCADE"
                }
            },
            "aplicacion_id": {
                "type": "UUID_V7",
                "allowNull": false,
                "nullable": false,
                "required": true,
                "foreignKey": {
                    "table": "producto.aplicaciones",
                    "column": "id",
                    "onDelete": "CASCADE"
                }
            },
            "build_number": {
                "type": "VARCHAR(20)",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "commit_hash": {
                "type": "VARCHAR(40)",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "escaneado_en": {
                "type": "TIMESTAMP",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": "CURRENT_TIMESTAMP"
            },
            "generado_por": {
                "type": "VARCHAR(100)",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "score_general": {
                "type": "DECIMAL(5,2)",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "nivel_riesgo": {
                "type": "VARCHAR(10)",
                "allowNull": false,
                "nullable": false,
                "required": true
            },
            "archivos_total": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "funciones_total": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "clases_total": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "dominios_negocio": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "metricas": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "arquitectura": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "seguridad": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "rendimiento": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "negocio": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "cumplimiento": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "created_at": {
                "type": "TIMESTAMP",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "updated_at": {
                "type": "TIMESTAMP",
                "allowNull": true,
                "nullable": true,
                "required": false
            }
        }
    },
    data: [
        {
            "id": "01961234-0000-7000-8000-000000000003",
            "activo_id": "00000000-0000-0000-0000-000000000000",
            "aplicacion_id": "00000000-0000-0000-0000-000000000000",
            "build_number": "#000",
            "commit_hash": "0000000000000000000000000000000000000000",
            "escaneado_en": "NOW()",
            "generado_por": "ejemplo-borrar",
            "score_general": 0.00,
            "nivel_riesgo": "LOW",
            "archivos_total": 0,
            "funciones_total": 0,
            "clases_total": 0,
            "dominios_negocio": null,
            "metricas": null,
            "arquitectura": null,
            "seguridad": null,
            "rendimiento": null,
            "negocio": null,
            "cumplimiento": null,
            "created_at": "NOW()",
            "updated_at": "NOW()"
        }
    ]
};
