// Copyright (c) 2026 Jean-Baptiste Meyer
// SPDX-License-Identifier: MIT

//
//  Item.swift
//  Meet Your Memory
//
//  Created by Jean-Baptiste Meyer on 7/30/26.
//

import Foundation
import SwiftData

@Model
final class Item {
    var timestamp: Date

    init(timestamp: Date) {
        self.timestamp = timestamp
    }
}
