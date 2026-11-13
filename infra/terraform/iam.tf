# The ingest user: least privilege. It can list its own prefixes and read/write raw, state
# and ops files under dev/ and prod/. It cannot delete anything or touch other buckets.
resource "aws_iam_user" "ingest" {
  name = "job-radar-ingest"
}

resource "aws_iam_user_policy" "ingest_s3" {
  name = "job-radar-ingest-s3"
  user = aws_iam_user.ingest.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ListOwnPrefixes"
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.raw.arn
        Condition = { StringLike = { "s3:prefix" = ["dev/*", "prod/*"] } }
      },
      {
        Sid    = "ReadWriteRawStateOps"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject"]
        Resource = [
          for p in ["dev/raw", "dev/state", "dev/ops", "prod/raw", "prod/state", "prod/ops"] :
          "${aws_s3_bucket.raw.arn}/${p}/*"
        ]
      },
    ]
  })
}
