#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
腾讯云免费 SSL 证书 — 到期监控 & 自动续期脚本
=============================================================================
功能：
  1. 列出账号下所有免费证书，展示到期时间与剩余天数
  2. 到期前 N 天自动申请新证书（默认 DNS_AUTO，需域名在腾讯云解析）
  3. 等待签发后自动下载 Nginx 格式证书到指定目录
  4. 可配合 crontab 实现全自动运行

依赖安装：
  pip install tencentcloud-sdk-python requests

配置方法（三选一，优先级从高到低）：
  A) 环境变量：
       export TENCENT_SECRET_ID="AKIDxxxxxxxxxx"
       export TENCENT_SECRET_KEY="xxxxxxxxxxxxxxxx"
  B) 在当前目录创建 .env 文件：
       TENCENT_SECRET_ID=AKIDxxxxxxxxxx
       TENCENT_SECRET_KEY=xxxxxxxxxxxxxxxx
  C) 直接修改下方 CONFIG 中的 secret_id / secret_key

crontab 示例（每周一早 9 点，与历史设定一致）：
  0 9 * * 1 /usr/bin/python3 /root/ssl_auto_renew.py >> /var/log/ssl-renew.log 2>&1

=============================================================================
"""

import os
import sys
import json
import time
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

# ======================== 用户可配置区域 ========================

CONFIG = {
    # ---------- 密钥（建议用环境变量，不要明文写在这里）----------
    "secret_id": os.environ.get("TENCENT_SECRET_ID", ""),
    "secret_key": os.environ.get("TENCENT_SECRET_KEY", ""),

    # ---------- 监控策略 ----------
    "renew_days_before": 25,          # 到期前多少天触发自动续期（免费证书 90 天有效期，建议 20~30 天）
    "wait_issue_timeout": 600,        # 申请后等待签发的最大秒数（默认 10 分钟）
    "poll_interval": 10,              # 轮询签发状态的间隔秒数

    # ---------- 域名白名单 ----------
    # 只监控这些域名，留空则监控所有免费证书
    # 例如: ["cloud.ziwi.cn", "heartbeat.ziwi.cn", "school.ziwi.cn"]
    "monitor_domains": [],

    # ---------- 下载与部署 ----------
    "download_dir": "/etc/nginx/ssl",          # 证书下载目录（Nginx 格式 zip）
    "service_type": "nginx",                   # 下载格式：nginx / apache / tomcat / iis / jks / other
    "auto_deploy": False,                      # 是否自动解压并覆盖部署（谨慎开启！）
    "nginx_cert_dir": "/etc/nginx/certs",      # 部署目标目录（auto_deploy=True 时生效）
    "nginx_reload_cmd": "systemctl reload nginx",  # 部署后 reload 命令
}

# ======================== 以下为脚本主体，一般无需修改 ========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ssl-monitor")


def load_dotenv(path: str = ".env") -> None:
    """加载 .env 文件中的环境变量"""
    if os.path.isfile(path):
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()


def check_config() -> bool:
    """校验配置是否完整"""
    if not CONFIG["secret_id"] or not CONFIG["secret_key"]:
        log.error("缺少 SecretId/SecretKey，请通过环境变量或 .env 文件配置")
        return False
    if not os.path.isdir(CONFIG["download_dir"]):
        try:
            os.makedirs(CONFIG["download_dir"], exist_ok=True)
            log.info(f"创建下载目录: {CONFIG['download_dir']}")
        except Exception as e:
            log.error(f"无法创建下载目录 {CONFIG['download_dir']}: {e}")
            return False
    return True


def get_ssl_client():
    """初始化腾讯云 SSL 客户端"""
    from tencentcloud.common import credential
    from tencentcloud.ssl.v20191205 import ssl_client

    cred = credential.Credential(CONFIG["secret_id"], CONFIG["secret_key"])
    return ssl_client.SslClient(cred, "")


def list_certificates(client) -> list:
    """获取所有已签发的免费证书"""
    from tencentcloud.ssl.v20191205 import models

    all_certs = []
    offset = 0
    limit = 100

    while True:
        req = models.DescribeCertificatesRequest()
        req.Offset = offset
        req.Limit = limit
        req.CertificateStatus = [1]  # 1 = 已签发
        req.CertificateType = ["CA"]  # CA 签发的证书

        resp = client.DescribeCertificates(req)
        certs = json.loads(resp.to_json_string())
        total = certs.get("TotalCount", 0)
        items = certs.get("Certificates", [])

        for cert in items:
            # 只监控免费证书 (TrustAsia C1 DV Free, PackageType 83)
            if cert.get("PackageType") == "83" or "Free" in cert.get("ProductZhName", ""):
                if not CONFIG["monitor_domains"] or cert.get("Domain") in CONFIG["monitor_domains"]:
                    all_certs.append(cert)

        offset += limit
        if offset >= total:
            break

    return all_certs


def days_until(expire_time: str) -> int:
    """计算距离到期还有多少天"""
    expire_dt = datetime.strptime(expire_time, "%Y-%m-%d %H:%M:%S")
    return (expire_dt - datetime.now()).days


def apply_certificate(client, domain: str, old_cert_id: str = "") -> Optional[str]:
    """申请免费证书，返回新证书 ID"""
    from tencentcloud.ssl.v20191205 import models

    log.info(f"正在为 {domain} 申请免费证书 ...")
    req = models.ApplyCertificateRequest()
    req.DvAuthMethod = "DNS_AUTO"       # 自动 DNS 验证（域名需在腾讯云解析）
    req.DomainName = domain
    req.PackageType = "83"              # TrustAsia C1 DV Free
    req.ValidityPeriod = "3"            # 3 个月
    req.CsrEncryptAlgo = "RSA"

    if old_cert_id:
        req.OldCertificateId = old_cert_id
        log.info(f"  关联旧证书 ID: {old_cert_id}（可建立续费关系）")

    try:
        resp = client.ApplyCertificate(req)
        result = json.loads(resp.to_json_string())
        new_cert_id = result.get("CertificateId", "")
        log.info(f"  申请成功！新证书 ID: {new_cert_id}")
        return new_cert_id
    except Exception as e:
        log.error(f"  申请失败: {e}")
        return None


def wait_for_issue(client, cert_id: str) -> bool:
    """等待证书签发（状态码 1 = 已签发）"""
    from tencentcloud.ssl.v20191205 import models

    log.info(f"  等待证书 {cert_id} 签发 ...")
    waited = 0
    while waited < CONFIG["wait_issue_timeout"]:
        time.sleep(CONFIG["poll_interval"])
        waited += CONFIG["poll_interval"]

        req = models.DescribeCertificateRequest()
        req.CertificateId = cert_id
        resp = client.DescribeCertificate(req)
        detail = json.loads(resp.to_json_string())

        status = detail.get("Status", 0)
        status_map = {0: "审核中", 1: "已签发", 2: "审核失败", 3: "已过期", 4: "已吊销"}
        status_text = status_map.get(status, f"未知({status})")
        log.info(f"    状态: {status_text}（已等待 {waited}s）")

        if status == 1:
            log.info(f"  证书 {cert_id} 已签发！")
            return True
        elif status in (2, 3, 4):
            log.error(f"  证书 {cert_id} 签发失败，状态: {status_text}")
            return False

    log.error(f"  等待超时（{CONFIG['wait_issue_timeout']}s），证书 {cert_id} 仍未签发")
    return False


def download_certificate(client, cert_id: str, domain: str) -> Optional[str]:
    """下载 Nginx 格式证书到本地目录，返回保存路径"""
    from tencentcloud.ssl.v20191205 import models
    import requests

    log.info(f"  获取证书 {cert_id} 的下载链接 ...")
    req = models.DescribeDownloadCertificateUrlRequest()
    req.CertificateId = cert_id
    req.ServiceType = CONFIG["service_type"]

    resp = client.DescribeDownloadCertificateUrl(req)
    result = json.loads(resp.to_json_string())
    url = result.get("DownloadCertificateUrl", "")
    filename = result.get("DownloadFilename", f"{domain}_nginx.zip")

    if not url:
        log.error(f"  未获取到下载链接")
        return None

    log.info(f"  正在下载: {filename} ...")
    r = requests.get(url, timeout=60)
    if r.status_code != 200:
        log.error(f"  下载失败，HTTP {r.status_code}")
        return None

    save_path = os.path.join(CONFIG["download_dir"], filename)
    with open(save_path, "wb") as f:
        f.write(r.content)
    log.info(f"  已保存到: {save_path}")
    return save_path


def auto_deploy(zip_path: str, domain: str):
    """自动解压并部署证书到 Nginx 目录"""
    import zipfile
    import subprocess

    extract_dir = os.path.join(CONFIG["nginx_cert_dir"], domain)
    os.makedirs(extract_dir, exist_ok=True)

    log.info(f"  解压到: {extract_dir}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    log.info(f"  文件列表: {os.listdir(extract_dir)}")
    log.info(f"  执行 Nginx reload ...")
    subprocess.run(CONFIG["nginx_reload_cmd"], shell=True, check=False)
    log.info(f"  {domain} 证书部署完成！")


def print_summary(certs: list):
    """打印证书汇总表"""
    log.info("=" * 70)
    log.info(f"{'域名':<30} {'证书ID':<16} {'到期时间':<22} {'剩余':>6}")
    log.info("-" * 70)

    for cert in certs:
        domain = cert.get("Domain", "?")
        cert_id = cert.get("CertificateId", "?")
        expire = cert.get("CertEndTime", "?")
        days = days_until(expire)
        flag = " ⚠️" if days <= CONFIG["renew_days_before"] else ""
        log.info(f"{domain:<30} {cert_id:<16} {expire:<22} {days:>4}天{flag}")

    log.info("=" * 70)


def main():
    log.info("===== 腾讯云 SSL 证书监控 & 自动续期 =====")

    # 加载 .env
    load_dotenv()
    if not check_config():
        sys.exit(1)

    client = get_ssl_client()

    # 1. 列出所有免费证书
    certs = list_certificates(client)
    log.info(f"共监控 {len(certs)} 张免费证书")
    print_summary(certs)

    # 2. 检查需要续期的证书
    renew_list = []
    for cert in certs:
        days = days_until(cert.get("CertEndTime", ""))
        if days <= CONFIG["renew_days_before"]:
            renew_list.append(cert)

    if not renew_list:
        log.info("所有证书尚未到续期阈值，无需操作。")
        return

    log.info(f"发现 {len(renew_list)} 张证书需要续期")

    # 3. 逐个续期
    for cert in renew_list:
        domain = cert.get("Domain", "")
        old_cert_id = cert.get("CertificateId", "")

        log.info(f"\n{'='*50}")
        log.info(f"处理: {domain}（旧证书: {old_cert_id}）")

        # 申请新证书
        new_cert_id = apply_certificate(client, domain, old_cert_id)
        if not new_cert_id:
            log.error(f"  {domain} 申请失败，跳过")
            continue

        # 等待签发
        if not wait_for_issue(client, new_cert_id):
            log.error(f"  {domain} 未能在超时前签发，新证书ID: {new_cert_id}，请手动处理")
            continue

        # 下载证书
        zip_path = download_certificate(client, new_cert_id, domain)
        if not zip_path:
            log.error(f"  {domain} 下载失败")
            continue

        # 自动部署（可选）
        if CONFIG["auto_deploy"]:
            auto_deploy(zip_path, domain)

    log.info("\n===== 自动续期任务完成 =====")


if __name__ == "__main__":
    main()