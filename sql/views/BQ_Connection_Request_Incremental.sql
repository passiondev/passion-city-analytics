CREATE OR ALTER VIEW dbo.BQ_Connection_Request_Incremental AS
SELECT
    Id,
    ConnectionOpportunityId,
    PersonAliasId,
    Comments,
    ConnectionStatusId,
    ConnectionState,
    FollowupDate,
    CampusId,
    AssignedGroupId,
    ConnectorPersonAliasId,
    CreatedDateTime,
    ModifiedDateTime,
    CreatedByPersonAliasId,
    ModifiedByPersonAliasId,
    CAST(Guid AS NVARCHAR(36))                              AS Guid,
    ForeignKey,
    CAST(ForeignGuid AS NVARCHAR(36))                       AS ForeignGuid,
    ForeignId,
    AssignedGroupMemberRoleId,
    AssignedGroupMemberStatus,
    AssignedGroupMemberAttributeValues,
    CreatedDateKey,
    [Order],
    ConnectionTypeId,
    ConnectionTypeSourceId,
    DueDate,
    DueSoonDate,
    ConnectedDateTime,
    WasCompletedOnTime,

    -- ingestion metadata for Make.com
    GETUTCDATE()                                            AS _loaded_at,
    'rock_rms'                                               AS _source_system

FROM dbo.ConnectionRequest
WHERE ModifiedDateTime >= (
        SELECT TOP(1) Last_Generated_Time
        FROM scheduler_log
        WHERE View_Name = 'BQ_Connection_Request_Incremental'
        ORDER BY Last_Generated_Time DESC
      )
  AND ModifiedDateTime <= CURRENT_TIMESTAMP