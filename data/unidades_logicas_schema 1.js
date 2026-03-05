module.exports = {
    schema: {
        "tableName": "unidades_logicas",
        "columns": {
            "id": {
                "type": "UUID_V7",
                "allowNull": false,
                "nullable": false,
                "required": true,
                "primaryKey": true,
                "default": "gen_random_uuid_v7()"
            },
            "archivo_id": {
                "type": "UUID_V7",
                "allowNull": false,
                "nullable": false,
                "required": true,
                "foreignKey": {
                    "table": "code.archivos_fuente",
                    "column": "id",
                    "onDelete": "CASCADE"
                }
            },
            "parent_id": {
                "type": "UUID_V7",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "foreignKey": {
                    "table": "code.unidades_logicas",
                    "column": "id",
                    "onDelete": "CASCADE"
                }
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
            "nombre": {
                "type": "VARCHAR(255)",
                "allowNull": false,
                "nullable": false,
                "required": true
            },
            "tipo": {
                "type": "VARCHAR(20)",
                "allowNull": false,
                "nullable": false,
                "required": true
            },
            "linea_inicio": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "linea_fin": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "complejidad": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "lineas_codigo": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "accede_bd": {
                "type": "BOOLEAN",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": false
            },
            "llamadas_externas": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "docstring": {
                "type": "BOOLEAN",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": false
            },
            "resumen": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "metadata": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "activo": {
                "type": "BOOLEAN",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": true
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
            "id": "01961234-0000-7000-8000-000000000002",
            "archivo_id": "01961234-0000-7000-8000-000000000001",
            "parent_id": null,
            "activo_id": "00000000-0000-0000-0000-000000000000",
            "aplicacion_id": "00000000-0000-0000-0000-000000000000",
            "nombre": "_EJEMPLO_BORRAR",
            "tipo": "CLASE",
            "linea_inicio": 1,
            "linea_fin": 100,
            "complejidad": 5,
            "lineas_codigo": 100,
            "accede_bd": false,
            "llamadas_externas": 0,
            "docstring": false,
            "resumen": "Registro de ejemplo - borrar después de crear la tabla",
            "metadata": null,
            "activo": true,
            "created_at": "NOW()",
            "updated_at": "NOW()"
        }
    ]
};
