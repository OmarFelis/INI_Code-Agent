module.exports = {
    schema: {
        "tableName": "archivos_fuente",
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
            "nombre": {
                "type": "VARCHAR(255)",
                "allowNull": false,
                "nullable": false,
                "required": true
            },
            "ruta_archivo": {
                "type": "TEXT",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "proposito": {
                "type": "VARCHAR(30)",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "capa": {
                "type": "VARCHAR(20)",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "lenguaje": {
                "type": "VARCHAR(20)",
                "allowNull": true,
                "nullable": true,
                "required": false
            },
            "total_funciones": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "total_clases": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "endpoints": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "operaciones_bd": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "llamadas_externas": {
                "type": "INTEGER",
                "allowNull": true,
                "nullable": true,
                "required": false,
                "default": 0
            },
            "complejidad_ciclomatica": {
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
            "id": "01961234-0000-7000-8000-000000000001",
            "activo_id": "00000000-0000-0000-0000-000000000000",
            "aplicacion_id": "00000000-0000-0000-0000-000000000000",
            "nombre": "_EJEMPLO_BORRAR",
            "ruta_archivo": "./src/main/java/ejemplo/Ejemplo.java",
            "proposito": "Controller",
            "capa": "Adaptador",
            "lenguaje": "Java",
            "total_funciones": 5,
            "total_clases": 1,
            "endpoints": 2,
            "operaciones_bd": 3,
            "llamadas_externas": 0,
            "complejidad_ciclomatica": 12,
            "lineas_codigo": 150,
            "resumen": "Registro de ejemplo - borrar después de crear la tabla",
            "metadata": null,
            "build_number": "#000",
            "commit_hash": "0000000000000000000000000000000000000000",
            "escaneado_en": "NOW()",
            "activo": true,
            "created_at": "NOW()",
            "updated_at": "NOW()"
        }
    ]
};
