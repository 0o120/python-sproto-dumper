-- A static schema module. The dumper does not execute this file.
return [=[
.Item {
    id 0 : integer
    name 1 : string
}

get_items 1 {
    request {
        category 0 : integer
    }
    response {
        items 0 : *Item(id)
    }
}

notify_ready 2 {
    request {}
}
]=]
