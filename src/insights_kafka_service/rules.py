from insights import make_metadata, rule

from . import PayloadMeta


@rule(PayloadMeta)
def payload(meta):
    extras = {}
    extras.update(meta.host)
    extras.update(meta.metadata)
    extras.update(meta.identity)

    return make_metadata(
        account=meta.account,
        request_id=meta.request_id,
        id=meta.id,
        **extras
    )
