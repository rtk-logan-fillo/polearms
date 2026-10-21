from datetime import datetime, timezone
from pathlib import Path

import yaml

DATETIME_FORMAT_MILLI = "%Y-%m-%dT%H:%M:%S.%f"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

FINGERPRINT_ALGORITHMS = {1: "md5", 2: "sha1", 3: "sha256"}

CLASS_MAP_PATH = Path(__file__).resolve().parent / "class_map.yaml"
with open(CLASS_MAP_PATH) as _class_map_file:
    TELEMETRY_TYPES = yaml.safe_load(_class_map_file)["classes"]


def _get(obj, path):
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def _first_evidence_value(evidences, path):
    if not evidences:
        return None
    return _get(evidences[0], path)


def _attack_values(attacks, path):
    values = []
    for attack in attacks:
        value = _get(attack, path)
        if value is not None:
            values.append(value)
    return values


def _hash_enrichments(evidences, algorithm_id):
    enrichments = []
    for evidence in evidences:
        for fingerprint in _get(evidence, "tls.certificate.fingerprints") or []:
            if fingerprint.get("algorithm_id") == algorithm_id:
                algorithm = FINGERPRINT_ALGORITHMS[algorithm_id]
                enrichments.append({"indicator": {"hash": {algorithm: fingerprint["value"]}}})
    return enrichments or None


def map_telemetry_types(class_uid):
    telemetry_type = TELEMETRY_TYPES.get(class_uid)
    return [telemetry_type] if telemetry_type else None


def map_time(time):
    datetime_format = DATETIME_FORMAT if time % 1000 == 0 else DATETIME_FORMAT_MILLI
    return datetime.fromtimestamp(time / 1000, tz=timezone.utc).strftime(datetime_format)


def map_activity_id(activity_id):
    return str(activity_id)

# TODO: this seems broken
# def map_malware_classifications(malware):
#     classifications = []
#     for item in malware:
#         classifications.extend(_get(item, "classifications") or [])
#     return _join(classifications)


def map_user_result_groups_uid(user_result_groups):
    return [group["uid"] for group in user_result_groups if "uid" in group]


def map_attack_tactic_id(attacks):
    return _attack_values(attacks, "tactic.uid") or None


def map_attack_tactic_name(attacks):
    return _attack_values(attacks, "tactic.name") or None


def map_attack_tactic_reference(attacks):
    return _attack_values(attacks, "tactic.src_url")


def map_attack_technique_id(attacks):
    return _attack_values(attacks, "technique.uid") or None


def map_attack_technique_name(attacks):
    return _attack_values(attacks, "technique.name") or None


def map_attack_technique_reference(attacks):
    return _attack_values(attacks, "technique.src_url")


def map_attack_subtechnique_reference(attacks):
    return _attack_values(attacks, "sub_technique.src_url")


def map_evidence_client_ip(evidences):
    return _first_evidence_value(evidences, "src_endpoint.ip")


def map_evidence_client_port(evidences):
    return _first_evidence_value(evidences, "src_endpoint.port")


def map_evidence_server_ip(evidences):
    return _first_evidence_value(evidences, "dst_endpoint.ip")


def map_evidence_geoip_city(evidences):
    return _first_evidence_value(evidences, "src_endpoint.location.city")


def map_evidence_geoip_country(evidences):
    return _first_evidence_value(evidences, "src_endpoint.location.country")


def map_evidence_geoip_latitude(evidences):
    value = _first_evidence_value(evidences, "src_endpoint.location.lat")
    return None if value is None else str(value)


def map_evidence_geoip_longitude(evidences):
    value = _first_evidence_value(evidences, "src_endpoint.location.long")
    return None if value is None else str(value)


def map_evidence_http_status(evidences):
    return _first_evidence_value(evidences, "http_response.code")


def map_evidence_http_method(evidences):
    return _first_evidence_value(evidences, "http_request.http_method")


def map_evidence_http_referer(evidences):
    return _first_evidence_value(evidences, "http_request.referrer")


def map_evidence_http_uri(evidences):
    return _first_evidence_value(evidences, "http_request.url.url_string")


def map_evidence_server_hostname(evidences):
    return _first_evidence_value(evidences, "dst_endpoint.hostname")


def map_evidence_server_port(evidences):
    return _first_evidence_value(evidences, "dst_endpoint.port")


def map_evidence_request_length(evidences):
    return _first_evidence_value(evidences, "http_request.length")


def map_evidence_request_scheme(evidences):
    return _first_evidence_value(evidences, "http_request.url.scheme")


def map_evidence_request_uid(evidences):
    return _first_evidence_value(evidences, "http_request.uid")


def map_evidence_request_path(evidences):
    return _first_evidence_value(evidences, "http_request.url.path")


def map_evidence_response_body_length(evidences):
    return _first_evidence_value(evidences, "http_response.body_length")


def map_evidence_security_zone(evidences):
    if not evidences:
        return None
    for resource in _get(evidences[0], "resources") or []:
        if isinstance(resource, dict) and "hostname" in resource:
            return resource["hostname"]
    return None


def map_evidence_user_agent(evidences):
    return _first_evidence_value(evidences, "http_request.user_agent")


def map_evidence_related_ip(evidences):
    related = []
    for index, evidence in enumerate(evidences):
        if index > 0:
            for path in ("src_endpoint.ip", "dst_endpoint.ip"):
                value = _get(evidence, path)
                if value is not None:
                    related.append(value)
        proxy_ip = _get(evidence, "dst_endpoint.proxy_endpoint.ip")
        if proxy_ip is not None:
            related.append(proxy_ip)
    return related or None


def map_evidence_hash_md5(evidences):
    return _hash_enrichments(evidences, 1)


def map_evidence_hash_sha1(evidences):
    return _hash_enrichments(evidences, 2)


def map_evidence_hash_sha256(evidences):
    return _hash_enrichments(evidences, 3)


def map_malware_scan_info_size(size):
    return [{"indicator": {"file": {"size": str(size)}}}]


def map_malware_scan_info_type(scan_type):
    return [{"indicator": {"file": {"type": scan_type}}}]


MAPPERS = {
    "map_telemetry_types": map_telemetry_types,
    "map_time": map_time,
    "map_activity_id": map_activity_id,
    "map_user_result_groups_uid": map_user_result_groups_uid,
    "map_attack_tactic_id": map_attack_tactic_id,
    "map_attack_tactic_name": map_attack_tactic_name,
    "map_attack_tactic_reference": map_attack_tactic_reference,
    "map_attack_technique_id": map_attack_technique_id,
    "map_attack_technique_name": map_attack_technique_name,
    "map_attack_technique_reference": map_attack_technique_reference,
    "map_attack_subtechnique_reference": map_attack_subtechnique_reference,
    "map_evidence_client_ip": map_evidence_client_ip,
    "map_evidence_client_port": map_evidence_client_port,
    "map_evidence_server_ip": map_evidence_server_ip,
    "map_evidence_geoip_city": map_evidence_geoip_city,
    "map_evidence_geoip_country": map_evidence_geoip_country,
    "map_evidence_geoip_latitude": map_evidence_geoip_latitude,
    "map_evidence_geoip_longitude": map_evidence_geoip_longitude,
    "map_evidence_http_status": map_evidence_http_status,
    "map_evidence_http_method": map_evidence_http_method,
    "map_evidence_http_referer": map_evidence_http_referer,
    "map_evidence_http_uri": map_evidence_http_uri,
    "map_evidence_server_hostname": map_evidence_server_hostname,
    "map_evidence_server_port": map_evidence_server_port,
    "map_evidence_request_length": map_evidence_request_length,
    "map_evidence_request_scheme": map_evidence_request_scheme,
    "map_evidence_request_uid": map_evidence_request_uid,
    "map_evidence_request_path": map_evidence_request_path,
    "map_evidence_response_body_length": map_evidence_response_body_length,
    "map_evidence_security_zone": map_evidence_security_zone,
    "map_evidence_user_agent": map_evidence_user_agent,
    "map_evidence_related_ip": map_evidence_related_ip,
    "map_evidence_hash_md5": map_evidence_hash_md5,
    "map_evidence_hash_sha1": map_evidence_hash_sha1,
    "map_evidence_hash_sha256": map_evidence_hash_sha256,
    "map_malware_scan_info_size": map_malware_scan_info_size,
    "map_malware_scan_info_type": map_malware_scan_info_type,
}


def get_mapper(name):
    return MAPPERS[name]
