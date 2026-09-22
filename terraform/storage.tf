data "oci_objectstorage_namespace" "current" {
  compartment_id = var.compartment_ocid
}

# R2 に加えた二次コピーの置き場。
# 一次を別事業者 (R2) に置いているのは、アカウント停止やリージョン障害で
# サーバーとバックアップを同時に失わないため (docs/spec/05-backup.md)。
resource "oci_objectstorage_bucket" "backup" {
  count          = var.enable_oci_backup ? 1 : 0
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.current.namespace
  name           = var.backup_bucket_name
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  versioning     = "Disabled"

  # prevent_destroy は付けていない。OCI は空でないバケットの削除を拒否するため、
  # 中身が入っている限り `terraform destroy` は自然に失敗して止まる。
  # lifecycle ブロックで固めると enable_oci_backup を false に戻せなくなる。
}

# 世代管理はスクリプト側ではなくバケット側で宣言的に行う。
# backup.sh が失敗しても保持期間は守られる。
resource "oci_objectstorage_object_lifecycle_policy" "backup_retention" {
  count     = var.enable_oci_backup && var.backup_remote_keep_days > 0 ? 1 : 0
  namespace = data.oci_objectstorage_namespace.current.namespace
  bucket    = oci_objectstorage_bucket.backup[0].name

  rules {
    name        = "delete-old-backups"
    action      = "DELETE"
    time_amount = var.backup_remote_keep_days
    time_unit   = "DAYS"
    is_enabled  = true

    target = "objects"
  }
}
