def classFactory(iface):
    from .public_services import PublicAgencyServicesPlugin
    return PublicAgencyServicesPlugin(iface)
