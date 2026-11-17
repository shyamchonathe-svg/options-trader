# Only /redirect reaches the trader; everything else is a 404. No access log (URLs carry request tokens).
DOMAIN {
	@redirect path /redirect
	handle @redirect {
		reverse_proxy 127.0.0.1:8001
	}
	handle {
		respond "not found" 404
	}
	log {
		output discard
	}
}
