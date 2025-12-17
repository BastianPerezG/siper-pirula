"""
Management command para realizar backups automáticos de la base de datos y archivos media.
Compatible con SQLite y MySQL, listo para PythonAnywhere.
Incluye subida opcional a AWS S3.

Uso:
    python manage.py backup_db
    python manage.py backup_db --retention 15
    python manage.py backup_db --no-media
    python manage.py backup_db --s3  # Sube a S3
"""
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea un backup de la base de datos y archivos media"

    def add_arguments(self, parser):
        parser.add_argument(
            "--retention",
            type=int,
            default=None,
            help="Días de retención de backups (default: BACKUP_RETENTION_DAYS en settings)",
        )
        parser.add_argument(
            "--no-media",
            action="store_true",
            help="No incluir la carpeta media en el backup",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Directorio donde guardar el backup (default: BACKUP_DIR en settings)",
        )
        parser.add_argument(
            "--s3",
            action="store_true",
            help="Subir el backup a AWS S3",
        )
        parser.add_argument(
            "--delete-local",
            action="store_true",
            help="Eliminar el backup local después de subirlo a S3 (solo con --s3)",
        )

    def handle(self, *args, **options):
        # Configuración
        backup_dir = Path(options["output_dir"] or getattr(settings, "BACKUP_DIR", settings.BASE_DIR / "backups"))
        retention_days = options["retention"] or getattr(settings, "BACKUP_RETENTION_DAYS", 30)
        include_media = not options["no_media"]
        upload_to_s3 = options["s3"]
        delete_local = options["delete_local"]
        
        # Crear directorio de backups si no existe
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Timestamp para el nombre del backup
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_name = f"backup_{timestamp}"
        backup_path = backup_dir / backup_name
        backup_path.mkdir(exist_ok=True)
        
        s3_url = None
        
        try:
            # 1. Backup de la base de datos
            self.stdout.write(self.style.NOTICE("Creando backup de base de datos..."))
            db_backup_file = self._backup_database(backup_path)
            
            # 2. Backup de archivos media (opcional)
            if include_media:
                self.stdout.write(self.style.NOTICE("Copiando archivos media..."))
                self._backup_media(backup_path)
            
            # 3. Comprimir todo en un ZIP
            self.stdout.write(self.style.NOTICE("Comprimiendo backup..."))
            zip_path = self._compress_backup(backup_path, backup_dir, backup_name)
            
            # 4. Eliminar carpeta temporal
            shutil.rmtree(backup_path)
            
            # 5. Subir a S3 (opcional)
            if upload_to_s3:
                self.stdout.write(self.style.NOTICE("Subiendo a AWS S3..."))
                s3_url = self._upload_to_s3(zip_path)
                
                # Eliminar local si se solicitó
                if delete_local:
                    zip_path.unlink()
                    self.stdout.write(f"   🗑️ Backup local eliminado")
            
            # 6. Limpiar backups antiguos (solo locales)
            if not delete_local:
                self.stdout.write(self.style.NOTICE(f"Limpiando backups mayores a {retention_days} días..."))
                deleted_count = self._cleanup_old_backups(backup_dir, retention_days)
            else:
                deleted_count = 0
            
            # 7. Registrar en bitácora
            self._log_backup(zip_path, success=True, s3_url=s3_url)
            
            # Resumen
            zip_size = zip_path.stat().st_size / (1024 * 1024) if zip_path.exists() else 0
            success_msg = f"\n✅ Backup completado exitosamente:\n"
            if not delete_local:
                success_msg += f"   📁 Archivo: {zip_path}\n"
                success_msg += f"   📊 Tamaño: {zip_size:.2f} MB\n"
            if s3_url:
                success_msg += f"   ☁️  S3: {s3_url}\n"
            success_msg += f"   🗑️  Backups eliminados: {deleted_count}"
            
            self.stdout.write(self.style.SUCCESS(success_msg))
            
        except Exception as e:
            # Limpiar en caso de error
            if backup_path.exists():
                shutil.rmtree(backup_path)
            
            # Registrar error en bitácora
            self._log_backup(None, success=False, error=str(e))
            
            raise CommandError(f"Error al crear backup: {e}")

    def _backup_database(self, backup_path: Path) -> Path:
        """Crea backup de la base de datos según el motor configurado."""
        db_config = settings.DATABASES["default"]
        engine = db_config["ENGINE"]
        
        if "sqlite3" in engine:
            return self._backup_sqlite(backup_path, db_config)
        elif "mysql" in engine:
            return self._backup_mysql(backup_path, db_config)
        else:
            raise CommandError(f"Motor de base de datos no soportado: {engine}")

    def _backup_sqlite(self, backup_path: Path, db_config: dict) -> Path:
        """Copia el archivo SQLite."""
        db_file = Path(db_config["NAME"])
        if not db_file.exists():
            raise CommandError(f"Archivo de base de datos no encontrado: {db_file}")
        
        dest_file = backup_path / "database.sqlite3"
        shutil.copy2(db_file, dest_file)
        self.stdout.write(f"   SQLite copiado: {db_file.name}")
        return dest_file

    def _backup_mysql(self, backup_path: Path, db_config: dict) -> Path:
        """Ejecuta mysqldump para crear backup de MySQL."""
        dest_file = backup_path / "database.sql"
        
        cmd = [
            "mysqldump",
            f"--host={db_config.get('HOST', 'localhost')}",
            f"--port={db_config.get('PORT', '3306')}",
            f"--user={db_config['USER']}",
            f"--password={db_config['PASSWORD']}",
            "--single-transaction",
            "--routines",
            "--triggers",
            db_config["NAME"],
        ]
        
        try:
            with open(dest_file, "w") as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, check=True)
            self.stdout.write(f"   MySQL dump creado: {db_config['NAME']}")
            return dest_file
        except subprocess.CalledProcessError as e:
            raise CommandError(f"Error en mysqldump: {e.stderr.decode()}")
        except FileNotFoundError:
            raise CommandError(
                "mysqldump no encontrado. Asegúrate de que MySQL client esté instalado."
            )

    def _backup_media(self, backup_path: Path):
        """Copia la carpeta media al backup."""
        media_root = Path(settings.MEDIA_ROOT)
        if not media_root.exists():
            self.stdout.write(self.style.WARNING("   Carpeta media no existe, omitiendo..."))
            return
        
        media_dest = backup_path / "media"
        shutil.copytree(media_root, media_dest, dirs_exist_ok=True)
        
        # Contar archivos copiados
        file_count = sum(1 for _ in media_dest.rglob("*") if _.is_file())
        self.stdout.write(f"   Media copiado: {file_count} archivos")

    def _compress_backup(self, backup_path: Path, backup_dir: Path, backup_name: str) -> Path:
        """Comprime la carpeta de backup en un archivo ZIP."""
        zip_path = backup_dir / f"{backup_name}.zip"
        
        with ZipFile(zip_path, "w") as zipf:
            for file_path in backup_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(backup_path)
                    zipf.write(file_path, arcname)
        
        return zip_path

    def _upload_to_s3(self, zip_path: Path) -> str:
        """Sube el archivo de backup a AWS S3."""
        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError
        except ImportError:
            raise CommandError(
                "boto3 no está instalado. Ejecuta: pip install boto3"
            )
        
        # Obtener configuración de S3
        bucket_name = getattr(settings, "AWS_BACKUP_BUCKET", None)
        if not bucket_name:
            raise CommandError(
                "AWS_BACKUP_BUCKET no está configurado en settings.py"
            )
        
        # Configurar cliente S3
        aws_access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
        aws_secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
        aws_session_token = getattr(settings, "AWS_SESSION_TOKEN", None)
        aws_region = getattr(settings, "AWS_REGION", "us-east-1")
        
        try:
            if aws_access_key and aws_secret_key:
                # Configuración para AWS Academy (con session token) o cuenta normal
                client_kwargs = {
                    "aws_access_key_id": aws_access_key,
                    "aws_secret_access_key": aws_secret_key,
                    "region_name": aws_region,
                }
                if aws_session_token:
                    client_kwargs["aws_session_token"] = aws_session_token
                
                s3_client = boto3.client("s3", **client_kwargs)
            else:
                # Usar credenciales del ambiente o IAM role
                s3_client = boto3.client("s3", region_name=aws_region)
            
            # Nombre del archivo en S3 (con prefijo de carpeta)
            s3_key = f"backups/{zip_path.name}"
            
            # Subir archivo
            s3_client.upload_file(
                str(zip_path),
                bucket_name,
                s3_key,
                ExtraArgs={
                    "StorageClass": "STANDARD_IA",  # Más económico para backups
                }
            )
            
            s3_url = f"s3://{bucket_name}/{s3_key}"
            self.stdout.write(f"   ☁️ Subido a: {s3_url}")
            return s3_url
            
        except NoCredentialsError:
            raise CommandError(
                "Credenciales de AWS no encontradas. Configura AWS_ACCESS_KEY_ID y "
                "AWS_SECRET_ACCESS_KEY en settings.py o en variables de ambiente."
            )
        except ClientError as e:
            raise CommandError(f"Error al subir a S3: {e}")

    def _cleanup_old_backups(self, backup_dir: Path, retention_days: int) -> int:
        """Elimina backups más antiguos que retention_days."""
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0
        
        for backup_file in backup_dir.glob("backup_*.zip"):
            # Extraer fecha del nombre: backup_2025-12-16_03-00-00.zip
            try:
                name_parts = backup_file.stem.split("_", 1)
                if len(name_parts) < 2:
                    continue
                date_str = name_parts[1].replace("_", " ").replace("-", ":", 2).replace(":", "-", 2)
                # Formato final: 2025-12-16 03:00:00
                file_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                
                if file_date < cutoff_date:
                    backup_file.unlink()
                    deleted_count += 1
                    self.stdout.write(f"   🗑️ Eliminado: {backup_file.name}")
            except (ValueError, IndexError):
                # Si no se puede parsear la fecha, ignorar
                continue
        
        return deleted_count

    def _log_backup(self, backup_path: Path, success: bool, error: str = None, s3_url: str = None):
        """Registra el backup en la bitácora del sistema."""
        try:
            from core.utils import registrar_bitacora_estructurada
            from core.models import Negocio
            
            negocio = Negocio.objects.first()
            if not negocio:
                return
            
            if success:
                detalles = {
                    "archivo": str(backup_path) if backup_path else None,
                    "tamaño_mb": round(backup_path.stat().st_size / (1024 * 1024), 2) if backup_path and backup_path.exists() else None,
                    "tipo": "automatico",
                }
                if s3_url:
                    detalles["s3_url"] = s3_url
                    
                accion = f"Backup creado exitosamente: {backup_path.name if backup_path else 'N/A'}"
                if s3_url:
                    accion += f" (subido a S3)"
                tipo_accion = "BACKUP_EXITOSO"
            else:
                detalles = {
                    "error": error,
                    "tipo": "automatico",
                }
                accion = f"Error al crear backup: {error}"
                tipo_accion = "BACKUP_ERROR"
            
            registrar_bitacora_estructurada(
                negocio=negocio,
                usuario=None,  # Backup automático sin usuario
                tipo_accion=tipo_accion,
                nombre_modelo="Sistema",
                accion=accion,
                entidad_id=0,
                detalles=detalles,
            )
        except Exception as e:
            # Si falla el log, solo mostrar warning
            self.stdout.write(self.style.WARNING(f"   ⚠️ No se pudo registrar en bitácora: {e}"))
