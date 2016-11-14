from wsgi.sub_connections import SCStorage

sc_store = SCStorage()

def form_sub_connections_result():
    f_subs = sc_store.get_subs_info()

