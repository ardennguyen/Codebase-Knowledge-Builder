from pocketflow import Flow
from nodes import (
    FetchRepo,
    ContextRouter,
    MapAbstractions,
    ReduceAbstractions,
    IdentifyAbstractions,
    AnalyzeRelationships,
    OrderChapters,
    WriteChapters,
    CombineTutorial
)

def create_tutorial_flow():
    fetch_repo = FetchRepo()
    context_router = ContextRouter()
    map_abstractions = MapAbstractions(max_retries=5, wait=20)
    reduce_abstractions = ReduceAbstractions(max_retries=5, wait=20)
    identify_abstractions = IdentifyAbstractions(max_retries=5, wait=20)
    analyze_relationships = AnalyzeRelationships(max_retries=5, wait=20)
    order_chapters = OrderChapters(max_retries=5, wait=20)
    write_chapters = WriteChapters(max_retries=5, wait=20)
    combine_tutorial = CombineTutorial()

    fetch_repo >> context_router
    
    context_router - "direct" >> identify_abstractions
    context_router - "batch" >> map_abstractions
    map_abstractions >> reduce_abstractions
    
    identify_abstractions >> analyze_relationships
    reduce_abstractions >> analyze_relationships
    
    analyze_relationships >> order_chapters
    order_chapters >> write_chapters
    write_chapters >> combine_tutorial

    return Flow(start=fetch_repo)
