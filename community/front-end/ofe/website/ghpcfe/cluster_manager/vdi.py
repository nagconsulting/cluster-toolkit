
import subprocess
import os
import logging

# Configure logging to output debug information.
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

NGINX_MAPPING_FILE = '/opt/gcluster/cluster-toolkit/community/front-end/ofe/website/guac_mapping.conf'


def generate_mapping_config(instance_mapping):
    """
    Generate an Nginx map block from a dictionary of instance names to IP addresses.
    Always include a default (empty string) so that $guac_backend is defined (for NGINX).
    """
    logger.debug("Generating Nginx mapping configuration.")
    lines = []
    lines.append("map $instance $guac_backend {")
    lines.append('    default "";')
    for instance, ip in instance_mapping.items():
        lines.append(f"    {instance} {ip};")
        logger.debug("Mapping instance '%s' to IP '%s'.", instance, ip)
    lines.append("}")
    config_text = "\n".join(lines)
    logger.debug("Generated configuration:\n%s", config_text)
    return config_text


def update_nginx_mapping(instance_mapping):
    """
    Write the mapping file and reload Gcluster Nginx service.
    
    :param instance_mapping: A dict mapping instance names to backend IPs.
    """
    logger.info("Updating Nginx mapping with %d entries.", len(instance_mapping))
    config_text = generate_mapping_config(instance_mapping)
    try:
        with open(NGINX_MAPPING_FILE, 'w') as f:
            f.write(config_text)
        logger.info("Successfully wrote mapping config to %s.", NGINX_MAPPING_FILE)
        
        # Reload Gcluster Nginx
        logger.info("Reloading Gcluster Nginx.")
        subprocess.check_call(['sudo', 'systemctl', 'reload', 'gcluster'])
        logger.info("Gcluster Nginx reloaded successfully.")
    except Exception as e:
        logger.error("Error updating Nginx mapping: %s", e, exc_info=True)


def add_guac_instance(instance_name, backend_ip):
    """
    Add a Guacamole instance to the mapping.
    
    :param instance_name: Unique identifier for the Guacamole instance.
    :param backend_ip: The IP address for the Guacamole backend.
    """
    logger.info("Adding Guacamole instance '%s' with IP '%s'.", instance_name, backend_ip)
    mapping = get_current_mapping()
    mapping[instance_name] = backend_ip
    update_nginx_mapping(mapping)


def remove_guac_instance(instance_name):
    """
    Remove a Guacamole instance from the mapping.
    
    :param instance_name: Unique identifier for the Guacamole instance.
    """
    logger.info("Removing Guacamole instance '%s'.", instance_name)
    mapping = get_current_mapping()
    if instance_name in mapping:
        del mapping[instance_name]
        logger.debug("Instance '%s' removed from mapping.", instance_name)
        update_nginx_mapping(mapping)
    else:
        logger.warning("Instance '%s' not found in the current mapping.", instance_name)


def get_current_mapping():
    """
    Read the current mapping from the Nginx snippet file.
    If the file doesn’t exist or cannot be parsed, return an empty mapping.
    """
    logger.info("Reading current mapping from %s.", NGINX_MAPPING_FILE)
    mapping = {}
    if not os.path.exists(NGINX_MAPPING_FILE):
        logger.warning("Mapping file %s does not exist.", NGINX_MAPPING_FILE)
        return mapping

    try:
        with open(NGINX_MAPPING_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("default") or line.startswith("map") or line.startswith("}"):
                    continue
                # Expect lines of the form: instanceName  IP;
                parts = line.rstrip(';').split()
                if len(parts) == 2:
                    instance, ip = parts
                    mapping[instance] = ip
                    logger.debug("Found mapping: %s -> %s", instance, ip)
    except Exception as e:
        logger.error("Error reading mapping file: %s", e, exc_info=True)
        return {}
    return mapping
