CREATE OR ALTER VIEW dbo.BQ_Financial_Account_Incremental AS
SELECT
    Id,
    ParentAccountId,
    CampusId,
    Name,
    PublicName,
    Description,
    IsTaxDeductible,
    GlCode,
    [Order],
    IsActive,
    StartDate,
    EndDate,
    AccountTypeValueId,
    CAST(Guid AS NVARCHAR(36))                              AS Guid,
    CreatedDateTime,
    ModifiedDateTime,
    CreatedByPersonAliasId,
    ModifiedByPersonAliasId,
    ForeignKey,
    ImageBinaryFileId,
    Url,
    PublicDescription,
    IsPublic,
    CAST(ForeignGuid AS NVARCHAR(36))                       AS ForeignGuid,
    ForeignId,
    UsesCampusChildAccounts,

    -- ingestion metadata for Make.com
    GETUTCDATE()                                            AS _loaded_at,
    'rock_rms'                                               AS _source_system

FROM dbo.FinancialAccount
WHERE ModifiedDateTime >= (
        SELECT TOP(1) Last_Generated_Time
        FROM scheduler_log
        WHERE View_Name = 'BQ_Financial_Account_Incremental'
        ORDER BY Last_Generated_Time DESC
      )
  AND ModifiedDateTime <= CURRENT_TIMESTAMP