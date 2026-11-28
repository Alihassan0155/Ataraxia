"""Stage 1: local, read-only recommendation features."""
from .catalogue import Catalogue, VideoFeatures, build_catalogue, load_local_database, load_local_package

__all__ = ['Catalogue', 'VideoFeatures', 'build_catalogue', 'load_local_database', 'load_local_package']

from .retrieval import (AffectFeatures, Candidate, CandidateRetriever, RetrievalConfig,
                        RetrievalResult, RetrievalState, StrategyEligibility)

__all__ += ["AffectFeatures", "Candidate", "CandidateRetriever", "RetrievalConfig",
            "RetrievalResult", "RetrievalState", "StrategyEligibility"]

from .four_pools import FourPoolResult, FourPoolRetriever, POOL_ORDER

__all__ += ['FourPoolResult', 'FourPoolRetriever', 'POOL_ORDER']
