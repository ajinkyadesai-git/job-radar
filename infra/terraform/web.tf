# The web app (T42): a private S3 bucket behind CloudFront.
#
#   /          -> the React build in S3 (only CloudFront can read the bucket)
#   /api/*     -> the API on Lambda; CloudFront strips "/api" and adds the X-API-Key header,
#                 so the key never reaches the browser. /ask has its own daily cap.
#
# The API key is read from SSM at plan time and kept in CloudFront's config; Terraform state
# therefore holds it, and state stays on the laptop, git-ignored (as before).

resource "aws_s3_bucket" "web" {
  bucket = "${aws_s3_bucket.raw.bucket}-web"
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "job-radar-web"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# "/api/jobs/today" -> "/jobs/today" before the request goes to the API.
resource "aws_cloudfront_function" "strip_api" {
  name    = "job-radar-strip-api-prefix"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      if (request.uri.indexOf('/api/') === 0) {
        request.uri = request.uri.substring(4);
      }
      return request;
    }
  EOT
}

data "aws_ssm_parameter" "api_key" {
  name            = "${local.ssm_prefix}JOBRADAR_API_KEY"
  with_decryption = true
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_but_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

locals {
  api_domain = trimsuffix(trimprefix(aws_lambda_function_url.api.function_url, "https://"), "/")
}

resource "aws_cloudfront_distribution" "web" {
  enabled             = true
  comment             = "Job Radar web app"
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # North America and Europe edges: the cheapest tier
  http_version        = "http2and3"

  origin {
    origin_id                = "site"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = local.api_domain
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
      origin_read_timeout    = 60 # /ask can take a while
    }
    custom_header {
      name  = "X-API-Key"
      value = data.aws_ssm_parameter.api_key.value
    }
  }

  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
  }

  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_but_host.id
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.strip_api.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# Only this CloudFront distribution may read the site files.
resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.web.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.web.arn } }
    }]
  })
}

# The deploy role (OIDC, main only) may upload the build and clear CloudFront's cache.
resource "aws_iam_role_policy" "github_deploy_web" {
  name = "publish-web-app"
  role = aws_iam_role.github_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.web.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.web.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
        Resource = aws_cloudfront_distribution.web.arn
      },
    ]
  })
}

output "web_url" {
  description = "The web app"
  value       = "https://${aws_cloudfront_distribution.web.domain_name}"
}

output "web_bucket" {
  description = "Where the web build is uploaded"
  value       = aws_s3_bucket.web.bucket
}

output "web_distribution_id" {
  description = "CloudFront distribution (for cache invalidation after a deploy)"
  value       = aws_cloudfront_distribution.web.id
}
